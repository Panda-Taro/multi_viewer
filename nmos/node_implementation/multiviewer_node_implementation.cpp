// nmos/node_implementation/multiviewer_node_implementation.cpp
//
// 対応要件: ④-7, ⑦ (NMOS Receiverロールのみ、Senderは一切生成しない)
//
// これは nmos-cpp (https://github.com/sony/nmos-cpp) の
// `Development/nmos-cpp-node/node_implementation.cpp` を置き換える形で
// ビルドに組み込む実装である (nmos/scripts/build_nmos_cpp.sh 参照)。
//
// nmos-cppの実際のAPI (nmos::resources, nmos::make_device, nmos::make_source,
// nmos::make_flow, nmos::make_receiver, nmos::details::make_connection_resource
// など。詳細は nmos-cpp の nmos/node_resources.h, nmos/connection_resources.h,
// nmos/node_server.h を参照) に基づき記述しているが、nmos-cppのバージョンにより
// 関数シグネチャが変わるため、実機ビルド時は組み込み先バージョンのヘッダーと
// 突き合わせて調整すること (README.md 記載の判断メモ)。
//
// 本ファイルは「実装の試み」として、5つのReceiver (video x4, audio x1) の
// リソースツリー (device -> source/flow(受信は本来不要だがnmos-cppの
// リソースモデル上、Receiverにひもづくsource/flowは生成しない。Receiverは
// Senderと異なりsource/flowを持たないことに注意) と、IS-05
// activateハンドラのみを実装し、Sender関連のAPI呼び出しは一切行わない。

#include <cpprest/json.h>
#include "nmos/activation_mode.h"
#include "nmos/api_utils.h"
#include "nmos/capabilities.h"
#include "nmos/connection_resources.h"
#include "nmos/format.h"
#include "nmos/id.h"
#include "nmos/is05_versions.h"
#include "nmos/model.h"
#include "nmos/node_resources.h"
#include "nmos/node_server.h"
#include "nmos/random.h"
#include "nmos/transport.h"

namespace multiviewer
{
    // 要件④-1,④-2: 映像Receiver x4 + 音声Receiver x1。Senderは絶対に作らない (⑦)。
    const int VIDEO_RECEIVER_COUNT = 4;

    // MultiViewer固有: bridgeサービスへactivate内容を転送するエンドポイント。
    // bridge/src/server.py が待ち受ける (④-7, bridge連携)。
    const std::string BRIDGE_ACTIVATE_URL = "http://127.0.0.1:8090/nmos/activate";

    nmos::id make_stable_receiver_id(const std::string& seed_id, int index, bool is_audio)
    {
        // 固定シードから決定論的にUUIDを導出し、再起動をまたいでも
        // 同じReceiver IDが維持されるようにする (NMOSコントローラ側の
        // 継続的な識別のため)。
        nmos::details::seeded_generator gen(seed_id + (is_audio ? "-audio-" : "-video-") + std::to_string(index));
        return nmos::make_repeatable_id(gen, seed_id);
    }

    web::json::value make_video_receiver_resource(const nmos::settings& settings, const nmos::id& device_id, int index)
    {
        using web::json::value;

        const auto id = make_stable_receiver_id(nmos::get_seed_id(settings), index, false);
        auto receiver = nmos::make_receiver(
            id,
            device_id,
            nmos::transports::rtp_mcast,
            { nmos::formats::video },
            { U("video/raw") },   // RFC4175 raw video (ST2110-20)
            settings
        );

        receiver[U("label")] = value::string(U("Video Receiver ") + utility::conversions::to_string_t(index + 1));
        receiver[U("description")] = value::string(U("ST2110-20 video receiver #") + utility::conversions::to_string_t(index + 1));

        // 要件⑥: 受信可能なフォーマット範囲をcapsとして表明する。
        value caps = value::object();
        caps[U("media_types")] = value::array(std::vector<value>{ value::string(U("video/raw")) });
        receiver[U("caps")] = caps;

        return receiver;
    }

    web::json::value make_audio_receiver_resource(const nmos::settings& settings, const nmos::id& device_id)
    {
        using web::json::value;

        const auto id = make_stable_receiver_id(nmos::get_seed_id(settings), 0, true);
        auto receiver = nmos::make_receiver(
            id,
            device_id,
            nmos::transports::rtp_mcast,
            { nmos::formats::audio },
            { U("audio/L24") },   // ST2110-30 PCM
            settings
        );

        receiver[U("label")] = value::string(U("Audio Receiver 1 (ch1/2)"));
        receiver[U("description")] = value::string(U("ST2110-30 audio receiver, channel 1/2 only"));

        value caps = value::object();
        caps[U("media_types")] = value::array(std::vector<value>{ value::string(U("audio/L24")) });
        receiver[U("caps")] = caps;

        return receiver;
    }

    // IS-05 activate (PATCH /connection/receivers/{id}/staged) を受けた際の
    // ハンドラ。SDPをパースしてbridgeへHTTPで転送し、bridgeがMTL RX設定を
    // 更新・IGMPv3 joinをトリガーする (④-7, bridge/README.md参照)。
    // nmos-cppの実際のフックポイントは `nmos::connection_activation_handler`。
    nmos::connection_activation_handler make_multiviewer_activation_handler(nmos::node_model& model)
    {
        return [&model](const nmos::resource& connection_resource)
        {
            const auto& staged = nmos::fields::endpoint_staged(connection_resource.data);
            const auto receiver_id = connection_resource.id;
            const auto sdp = web::json::value::null();  // 実装上はstagedからsender SDPを抽出

            // bridgeへHTTP POSTで通知 (実装はcpprestsdkのhttp_clientを使用)。
            // ここでは構造のみ示す。実処理は bridge/src/server.py の
            // /nmos/activate エンドポイントで受ける想定。
            web::json::value payload = web::json::value::object();
            payload[U("receiver_id")] = web::json::value::string(receiver_id);
            payload[U("staged")] = staged;

            // NOTE: 実際の非同期HTTP呼び出しは省略 (統合先nmos-cppの
            // イベントループ/executorに合わせて実装する必要があるため)。
        };
    }

    // node_implementation.cpp が公開すべき init 関数の実体。
    // nmos-cppのnode_serverはこの関数を呼んで初期リソースを登録する。
    void node_implementation_init(nmos::node_model& model)
    {
        const auto& settings = model.settings;
        const auto node_id = nmos::make_id();
        const auto device_id = nmos::make_id();

        auto node_resources = nmos::make_node_resources(node_id, settings);
        // device: Senderを一切持たない。receiversのみをぶら下げる。
        auto device = nmos::make_device(device_id, node_id, {}, /*receivers*/ {}, settings);

        std::vector<web::json::value> receivers;
        for (int i = 0; i < VIDEO_RECEIVER_COUNT; ++i)
        {
            receivers.push_back(make_video_receiver_resource(settings, device_id, i));
        }
        receivers.push_back(make_audio_receiver_resource(settings, device_id));

        // 要件④-7: Senderリソースはコード上、一切生成しない。
        // (make_sender / nmos::make_sender_resource 等の呼び出しは存在しない)

        for (auto& r : receivers)
        {
            nmos::experimental::insert_resource_after(0, model.node_resources, std::move(r));
        }

        model.connection_activation_handler = make_multiviewer_activation_handler(model);
    }
}
