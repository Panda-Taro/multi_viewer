// nmos/node_implementation/multiviewer_node_implementation.cpp
//
// 対応要件: ④-7, ⑦ (NMOS Receiverロールのみ、Senderは一切生成しない)
//
// nmos-cpp (https://github.com/sony/nmos-cpp) の
// `Development/nmos-cpp-node/node_implementation.cpp` を置き換える形で
// ビルドに組み込む実装 (nmos/scripts/build_nmos_cpp.sh 参照)。main.cpp・
// node_implementation.h はnmos-cpp本体のものをそのまま使うため、本ファイルは
// node_implementation.h が要求する以下3関数のみを実装する:
//   - validate_node_implementation_settings
//   - node_implementation_thread
//   - make_node_implementation
//
// 【2026-09 改訂】実機ビルドで判明したAPI不一致 (nmos::get_seed_id /
// nmos::make_node_resources / nmos::experimental::insert_resource_after /
// nmos::node_model::connection_activation_handler は現行nmos-cpp(master)には
// 存在しない) を修正するため、実際にmasterブランチのnmos-cppをclone・精査し、
// そこで使われている実APIパターン (Development/nmos-cpp-node/
// node_implementation.cpp のサンプル実装) に合わせて全面的に書き直した。
// 具体的な参照箇所:
//   - nmos::make_node / nmos::make_device / nmos::make_receiver /
//     nmos::make_audio_receiver / nmos::make_connection_rtp_receiver の
//     シグネチャ
//   - model.write_lock() 経由でのリソース挿入 (insert_resource + model.notify())
//   - nmos::connection_activation_handler の実シグネチャは
//     void(const nmos::resource&, const nmos::resource&) (Receiver本体の
//     resourceとIS-05 connection resourceの2引数)
//   - nmos::experimental::node_implementation はデフォルト構築後
//     .on_xxx(handler) を連鎖するfluent builder (model.connection_activation_handler
//     のような直接メンバ代入は存在しない)
//
// 本実装は要件④-7,⑦の通り、映像Receiver x4 + 音声Receiver x1のみを公開し、
// Sender/Source/Flowリソースは一切生成しない。ST2022-7 (⑤-2-1) のため全
// Receiverは常にAmber/Blue 2インターフェース構成とする。

#include "node_implementation.h"

#include <map>
#include "cpprest/host_utils.h" // for web::hosts::experimental::host_interface (full definition; nmos/settings.h etc. only forward-declare it)
#include "cpprest/http_client.h"
#include "cpprest/json.h"
#include "nmos/capabilities.h"
#include "nmos/certificate_handlers.h"
#include "nmos/clock_name.h"
#include "nmos/connection_api.h"
#include "nmos/connection_resources.h"
#include "nmos/format.h"
#include "nmos/media_type.h"
#include "nmos/model.h"
#include "nmos/node_interfaces.h"
#include "nmos/node_resource.h"
#include "nmos/node_resources.h"
#include "nmos/node_server.h"
#include "nmos/random.h"
#include "nmos/slog.h"
#include "nmos/transport.h"

namespace multiviewer
{
    // ログカテゴリ。名前空間スコープの static const として保持する。
    //
    // 【2026-09 実機デバッグで判明した修正】当初は
    // `nmos::stash_category(nmos::category{ "..." })` のように一時オブジェクトを
    // 直接渡していたが、`nmos::stash_category(const category&)` が返す
    // omanip_function はcategoryへの参照をキャプチャする実装であるため、
    // 呼び出し式の終わりで一時オブジェクトが破棄されるとダングリング参照になる。
    // ログ出力の度にこの壊れた参照を経由して文字列を再構築しようとして
    // SIGSEGV (std::string::_M_construct内でクラッシュ) していた。
    // nmos-cppの公式サンプル実装(Development/nmos-cpp-node/node_implementation.cpp)
    // と同様に、名前空間スコープの寿命の長いconstオブジェクトとして保持することで
    // 解消した。
    namespace categories
    {
        const nmos::category node_implementation{ "multiviewer_node_implementation" };
    }

    // 要件④-1,④-2: 映像Receiver x4 + 音声Receiver x1。Senderは絶対に作らない (⑦)。
    const int video_receiver_count = 4;

    // bridgeサービス (bridge/src/server.py) の通知先。
    // 要件④-7: IS-05 activateを受けてMTL RX設定を更新しIGMPv3 joinを行う。
    const utility::string_t bridge_activate_url = U("http://127.0.0.1:8090/nmos/activate");
    // 要件④-8-4-2-1補足仕様: IS-05 deactivate (staged/active master_enable=false
    // をactivate) を受けて、MTL Rxセッション停止+IGMPv3 leaveを行う。
    const utility::string_t bridge_deactivate_url = U("http://127.0.0.1:8090/nmos/deactivate");

    // receiver resource id (UUID) -> bridge向けラベル ("video-receiver-1" 等)。
    // bridge/src/translator.py の receiver_kind_and_index() が期待する形式に
    // 合わせる。node_implementation_thread()内でReceiver生成時に登録し、
    // 活性化ハンドラ(make_multiviewer_activation_handler)から参照する。
    // 単一プロセス内で書き込み(起動時1回)と読み取り(activate/deactivateの都度)
    // が競合しないよう、書き込みはnode_implementation_thread()の初期化フェーズ
    // (model.write_lock()保持中、他スレッドはまだactivateを起こせない)に限定する。
    std::map<nmos::id, utility::string_t> receiver_role_by_id;

    struct node_implementation_init_exception {};

    // 決定論的なリソースID (再起動をまたいでも同じIDを維持する。NMOSコントローラ
    // 側の継続的な識別のため)。
    nmos::id make_stable_id(const nmos::id& seed_id, const utility::string_t& path)
    {
        return nmos::make_repeatable_id(seed_id, path);
    }

    // settingsのhost_addressesで指定されたアドレスに対応するインターフェースを探す
    // (nmos-cppサンプル node_implementation.cpp の impl::find_interface と同等)。
    std::vector<web::hosts::experimental::host_interface>::const_iterator find_interface(
        const std::vector<web::hosts::experimental::host_interface>& interfaces, const utility::string_t& address)
    {
        return std::find_if(interfaces.begin(), interfaces.end(), [&](const web::hosts::experimental::host_interface& interface_)
        {
            return interface_.addresses.end() != std::find(interface_.addresses.begin(), interface_.addresses.end(), address);
        });
    }

    // 要件④-8-4-2-3-2 (各APIの送信元ポート、及びtransport paramsの"auto"解決):
    // Receiverのinterface_ip(Amber/Blue)のみを解決する。本システムはReceiver
    // 専用のため、Sender側のsource_ip/destination_ip解決ロジックは持たない。
    nmos::connection_resource_auto_resolver make_multiviewer_auto_resolver(const nmos::settings&)
    {
        using web::json::value;
        return [](const nmos::resource&, const nmos::resource& connection_resource, value& transport_params)
        {
            const auto& constraints = nmos::fields::endpoint_constraints(connection_resource.data);
            const bool smpte2022_7 = 1 < transport_params.size();
            nmos::details::resolve_auto(transport_params[0], nmos::fields::interface_ip, [&] { return web::json::front(nmos::fields::constraint_enum(constraints.at(0).at(nmos::fields::interface_ip))); });
            if (smpte2022_7) nmos::details::resolve_auto(transport_params[1], nmos::fields::interface_ip, [&] { return web::json::back(nmos::fields::constraint_enum(constraints.at(1).at(nmos::fields::interface_ip))); });
            nmos::resolve_rtp_auto(connection_resource.type, transport_params);
        };
    }

    // 要件④-7: IS-05 activateを受けてbridgeへ非同期HTTP POSTで転送する。
    // bridge/src/server.py の /nmos/activate エンドポイントが受け取り、SDP解析・
    // MTL RX設定更新・IGMPv3 joinを行う (bridge/README.md参照)。
    // bridgeが未起動でも例外を握りつぶし、NMOS側のactivate応答自体は成功させる
    // (activate自体の成功可否とbridge反映は疎結合にする設計判断)。
    //
    // 要件④-8-4-2-1補足仕様(2026-09追加): active.master_enable が false の
    // 場合は「activate」ではなく「deactivate」であるため、SDP解析を必要としない
    // bridge の /nmos/deactivate エンドポイントへ転送する。WebGUI手動トグルの
    // 通知先(/webgui/receiver-toggle)と同じ内部ロジック
    // (translator.apply_deactivate_request)を通ることで、WebGUIトグルと
    // IS-05のmaster_enableが同一の内部状態を指すようにする。
    nmos::connection_activation_handler make_multiviewer_activation_handler(slog::base_gate& gate)
    {
        return [&gate](const nmos::resource& resource, const nmos::resource& connection_resource)
        {
            const auto& active = connection_resource.data.at(nmos::fields::endpoint_active);
            const bool master_enable = active.has_field(nmos::fields::master_enable)
                ? nmos::fields::master_enable(active)
                : false;

            if (!master_enable)
            {
                const auto role_it = receiver_role_by_id.find(resource.id);
                if (receiver_role_by_id.end() == role_it)
                {
                    slog::log<slog::severities::warning>(gate, SLOG_FLF) << "Deactivating unknown receiver " << resource.id;
                    return;
                }
                const auto& receiver_role = role_it->second;

                slog::log<slog::severities::info>(gate, SLOG_FLF) << "Deactivating " << resource.id << " (role=" << receiver_role << ")";

                web::json::value payload = web::json::value::object();
                payload[U("receiver_role")] = web::json::value::string(receiver_role);
                payload[U("enabled")] = web::json::value::boolean(false);

                try
                {
                    auto client = std::make_shared<web::http::client::http_client>(bridge_deactivate_url);
                    web::http::http_request req(web::http::methods::POST);
                    req.headers().set_content_type(U("application/json"));
                    req.set_body(payload);
                    client->request(req).then([&gate, client](pplx::task<web::http::http_response> task)
                    {
                        try { task.get(); }
                        catch (const std::exception& e)
                        {
                            slog::log<slog::severities::warning>(gate, SLOG_FLF) << "bridge通知に失敗: " << e.what();
                        }
                    });
                }
                catch (const std::exception& e)
                {
                    slog::log<slog::severities::warning>(gate, SLOG_FLF) << "bridge通知に失敗: " << e.what();
                }
                return;
            }

            slog::log<slog::severities::info>(gate, SLOG_FLF) << "Activating " << resource.id;

            web::json::value payload = web::json::value::object();
            payload[U("receiver_id")] = web::json::value::string(resource.id);
            payload[U("active")] = active;

            try
            {
                auto client = std::make_shared<web::http::client::http_client>(bridge_activate_url);
                web::http::http_request req(web::http::methods::POST);
                req.headers().set_content_type(U("application/json"));
                req.set_body(payload);
                client->request(req).then([&gate, client](pplx::task<web::http::http_response> task)
                {
                    try { task.get(); }
                    catch (const std::exception& e)
                    {
                        slog::log<slog::severities::warning>(gate, SLOG_FLF) << "bridge通知に失敗: " << e.what();
                    }
                });
            }
            catch (const std::exception& e)
            {
                slog::log<slog::severities::warning>(gate, SLOG_FLF) << "bridge通知に失敗: " << e.what();
            }
        };
    }
}

// 要件に独自のnode設定は追加していないため、標準のプロパティ検証のみ行う。
void validate_node_implementation_settings(const nmos::settings& settings)
{
    nmos::validate_node_settings(settings);
}

// nmos-cppのnode_serverが起動時にバックグラウンドスレッドとして呼び出す。
// 映像Receiver x4 + 音声Receiver x1をモデルに登録した後、shutdown要求まで待機する
// (Receiver専用のためIS-12制御プロトコルやイベントシミュレーション等の追加処理は行わない)。
void node_implementation_thread(nmos::node_model& model, nmos::experimental::control_protocol_state&, slog::base_gate& gate_)
{
    nmos::details::omanip_gate gate{ gate_, nmos::stash_category(multiviewer::categories::node_implementation) };

    try
    {
        auto lock = model.write_lock(); // モデル更新にはロックが必要

        const auto seed_id = nmos::experimental::fields::seed_id(model.settings);
        const auto node_id = multiviewer::make_stable_id(seed_id, U("/node"));
        const auto device_id = multiviewer::make_stable_id(seed_id, U("/device"));

        const unsigned int delay_millis{ 0 };

        // モデル更新は書き込みロック済み・更新後にmodel.notify()するのが作法
        // (nmos-cppサンプル node_implementation.cpp の insert_resource_after と同等)。
        const auto insert_resource_after = [&model, &lock](unsigned int milliseconds, nmos::resources& resources, nmos::resource&& resource, slog::base_gate& gate)
        {
            if (nmos::details::wait_for(model.shutdown_condition, lock, bst::chrono::milliseconds(milliseconds), [&] { return model.shutdown; })) return false;
            const std::pair<nmos::id, nmos::type> id_type{ resource.id, resource.type };
            const bool success = insert_resource(resources, std::move(resource)).second;
            if (success)
                slog::log<slog::severities::info>(gate, SLOG_FLF) << "Updated model with " << id_type;
            else
                slog::log<slog::severities::severe>(gate, SLOG_FLF) << "Model update error: " << id_type;
            model.notify();
            return success;
        };

        // 要件⑤-2-1: ST2022-7のため全Receiverは常にAmber/Blue 2インターフェース。
        // settingsのhost_addresses配列の1番目/2番目をAmber/Blueとして扱う
        // (WebGUIのシステム設定 (④-8-4-3-1) で設定される想定。判断メモ:
        // どちらがAmber/Blueかを明示するsettingsキーは要件定義書にないため、
        // host_addressesの並び順をそのままAmber=primary, Blue=secondaryとした)。
        const auto host_interfaces = nmos::get_host_interfaces(model.settings);
        const auto& host_address = nmos::fields::host_address(model.settings);
        const auto& primary_address = model.settings.has_field(nmos::fields::host_addresses) ? web::json::front(nmos::fields::host_addresses(model.settings)).as_string() : host_address;
        const auto& secondary_address = model.settings.has_field(nmos::fields::host_addresses) ? web::json::back(nmos::fields::host_addresses(model.settings)).as_string() : host_address;
        const auto primary_interface_ = multiviewer::find_interface(host_interfaces, primary_address);
        const auto secondary_interface_ = multiviewer::find_interface(host_interfaces, secondary_address);
        if (host_interfaces.end() == primary_interface_ || host_interfaces.end() == secondary_interface_)
        {
            slog::log<slog::severities::severe>(gate, SLOG_FLF) << "ST2022-7用のAmber/Blueインターフェースがhost_addresses設定と対応しません";
            throw multiviewer::node_implementation_init_exception();
        }
        const auto& primary_interface = *primary_interface_;
        const auto& secondary_interface = *secondary_interface_;
        const std::vector<utility::string_t> interface_names{ primary_interface.name, secondary_interface.name };
        constexpr bool smpte2022_7 = true;

        // node
        {
            const auto clocks = web::json::value_of({ nmos::make_internal_clock(nmos::clock_names::clk0) });
            const auto interfaces = nmos::experimental::node_interfaces(host_interfaces);
            auto node = nmos::make_node(node_id, clocks, nmos::make_node_interfaces(interfaces), model.settings);
            if (!insert_resource_after(delay_millis, model.node_resources, std::move(node), gate)) throw multiviewer::node_implementation_init_exception();
        }

        // 要件④-7,⑦: deviceはSenderを一切持たない。receiver_idsのみ列挙する。
        std::vector<nmos::id> video_receiver_ids;
        for (int i = 0; i < multiviewer::video_receiver_count; ++i)
            video_receiver_ids.push_back(multiviewer::make_stable_id(seed_id, U("/receiver/video/") + utility::conversions::details::to_string_t(i)));
        const auto audio_receiver_id = multiviewer::make_stable_id(seed_id, U("/receiver/audio/0"));

        std::vector<nmos::id> receiver_ids = video_receiver_ids;
        receiver_ids.push_back(audio_receiver_id);

        {
            auto device = nmos::make_device(device_id, node_id, /* senders */ {}, receiver_ids, model.settings);
            if (!insert_resource_after(delay_millis, model.node_resources, std::move(device), gate)) throw multiviewer::node_implementation_init_exception();
        }

        const auto resolve_auto = multiviewer::make_multiviewer_auto_resolver(model.settings);

        // 受信側のIS-05 endpoint_constraints (interface_ip) を組み立てる共通処理。
        const auto set_interface_ip_constraints = [&](nmos::resource& connection_receiver)
        {
            connection_receiver.data[nmos::fields::endpoint_constraints][0][nmos::fields::interface_ip] = web::json::value_of({
                { nmos::fields::constraint_enum, web::json::value_from_elements(primary_interface.addresses) }
            });
            connection_receiver.data[nmos::fields::endpoint_constraints][1][nmos::fields::interface_ip] = web::json::value_of({
                { nmos::fields::constraint_enum, web::json::value_from_elements(secondary_interface.addresses) }
            });
        };

        // 要件④-1,⑥: 映像Receiver x4。デフォルト 1920x1080 59.94i 4:2:2 10bit SDR。
        // 実際のフォーマットはNMOS SDP (IS-05 activate) で上書きされる (④-1-3)。
        for (int i = 0; i < multiviewer::video_receiver_count; ++i)
        {
            const auto& receiver_id = video_receiver_ids[i];
            // 要件④-8-4-2-1補足仕様: bridgeがreceiver_role文字列で参照するための
            // id->role対応表 (bridge/src/translator.pyのreceiver_kind_and_index()
            // が期待する"video-receiver-<1始まり>"形式に合わせる)。
            multiviewer::receiver_role_by_id[receiver_id] = U("video-receiver-") + utility::conversions::details::to_string_t(i + 1);
            const auto video_type = nmos::media_types::video_raw;

            auto receiver = nmos::make_receiver(receiver_id, device_id, nmos::transports::rtp, interface_names, nmos::formats::video, { video_type }, model.settings);
            receiver.data[U("label")] = web::json::value::string(U("Video Receiver ") + utility::conversions::details::to_string_t(i + 1));
            receiver.data[U("description")] = web::json::value::string(U("ST2110-20 video receiver #") + utility::conversions::details::to_string_t(i + 1));
            receiver.data[nmos::fields::caps][nmos::fields::constraint_sets] = web::json::value_of({
                web::json::value_of({
                    { nmos::caps::format::frame_width, nmos::make_caps_integer_constraint({ 1920 }) },
                    { nmos::caps::format::frame_height, nmos::make_caps_integer_constraint({ 1080 }) },
                    { nmos::caps::format::color_sampling, nmos::make_caps_string_constraint({ U("YCbCr-4:2:2") }) }
                })
            });

            auto connection_receiver = nmos::make_connection_rtp_receiver(receiver_id, smpte2022_7);
            set_interface_ip_constraints(connection_receiver);
            resolve_auto(receiver, connection_receiver, connection_receiver.data[nmos::fields::endpoint_active][nmos::fields::transport_params]);

            if (!insert_resource_after(delay_millis, model.node_resources, std::move(receiver), gate)) throw multiviewer::node_implementation_init_exception();
            if (!insert_resource_after(delay_millis, model.connection_resources, std::move(connection_receiver), gate)) throw multiviewer::node_implementation_init_exception();
        }

        // 要件④-2,⑥: 音声Receiver x1 (ch1/2固定、48kHz、24bit PCM)。
        {
            multiviewer::receiver_role_by_id[audio_receiver_id] = U("audio-receiver-1");
            auto receiver = nmos::make_audio_receiver(audio_receiver_id, device_id, nmos::transports::rtp, interface_names, 24u, model.settings);
            receiver.data[U("label")] = web::json::value::string(U("Audio Receiver 1 (ch1/2)"));
            receiver.data[U("description")] = web::json::value::string(U("ST2110-30 audio receiver, channel 1/2 only"));
            receiver.data[nmos::fields::caps][nmos::fields::constraint_sets] = web::json::value_of({
                web::json::value_of({
                    { nmos::caps::format::channel_count, nmos::make_caps_integer_constraint({}, 1, 2) },
                    { nmos::caps::format::sample_rate, nmos::make_caps_rational_constraint({ { 48000, 1 } }) },
                    { nmos::caps::format::sample_depth, nmos::make_caps_integer_constraint({ 24 }) }
                })
            });

            auto connection_receiver = nmos::make_connection_rtp_receiver(audio_receiver_id, smpte2022_7);
            set_interface_ip_constraints(connection_receiver);
            resolve_auto(receiver, connection_receiver, connection_receiver.data[nmos::fields::endpoint_active][nmos::fields::transport_params]);

            if (!insert_resource_after(delay_millis, model.node_resources, std::move(receiver), gate)) throw multiviewer::node_implementation_init_exception();
            if (!insert_resource_after(delay_millis, model.connection_resources, std::move(connection_receiver), gate)) throw multiviewer::node_implementation_init_exception();
        }

        slog::log<slog::severities::info>(gate, SLOG_FLF) << "MultiViewer NMOS node initialized: 4 video receivers + 1 audio receiver (Sender/Source/Flow are never created)";

        // Receiver専用のため追加のバックグラウンド処理は不要。shutdownまで待機する。
        model.shutdown_condition.wait(lock, [&model] { return model.shutdown; });
    }
    catch (const multiviewer::node_implementation_init_exception&)
    {
        // 上でログ済み
    }
    catch (const web::json::json_exception& e)
    {
        slog::log<slog::severities::error>(gate, SLOG_FLF) << "JSON error: " << e.what();
    }
    catch (const std::exception& e)
    {
        slog::log<slog::severities::error>(gate, SLOG_FLF) << "Unexpected exception: " << e.what();
    }
}

// main.cppがサーバ起動前に呼び出し、node_server (nmos::experimental::node_implementation)
// に組み込むコールバック一式を構築する。Receiver専用のため、Sender用
// transportfile設定やIS-12/認可(OAuth)関連のコールバックは登録しない
// (nmos::experimental::node_implementationのデフォルト(no-op)のまま)。
nmos::experimental::node_implementation make_node_implementation(nmos::node_model& model, slog::base_gate& gate)
{
    return nmos::experimental::node_implementation()
        .on_load_server_certificates(nmos::make_load_server_certificates_handler(model.settings, gate))
        .on_load_dh_param(nmos::make_load_dh_param_handler(model.settings, gate))
        .on_load_ca_certificates(nmos::make_load_ca_certificates_handler(model.settings, gate))
        .on_resolve_auto(multiviewer::make_multiviewer_auto_resolver(model.settings))
        .on_connection_activated(multiviewer::make_multiviewer_activation_handler(gate));
}
