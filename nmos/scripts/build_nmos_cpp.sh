#!/usr/bin/env bash
# nmos/scripts/build_nmos_cpp.sh
# 対応要件: ④-7, 配置要件(初回セットアップ)
#
# nmos-cpp (https://github.com/sony/nmos-cpp) を取得し、本プロジェクト独自の
# node_implementation (../node_implementation/multiviewer_node_implementation.cpp)
# を組み込んだ上でビルドする。
set -euo pipefail

BUILD_DIR="${BUILD_DIR:-/opt/multiviewer/build}"
NMOS_CPP_REF="${NMOS_CPP_REF:-master}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[build_nmos_cpp] $*"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "root権限で実行してください (sudo $0)" >&2
    exit 1
  fi
}

install_deps() {
  log "依存パッケージをインストール (Boost, cpprestsdk, OpenSSL, Avahi等)"
  apt-get update -y
  apt-get install -y \
    cmake build-essential git \
    libboost-all-dev libssl-dev \
    libwebsocketpp-dev nlohmann-json3-dev \
    libavahi-client-dev libavahi-common-dev \
    libavahi-compat-libdnssd-dev \
    libcpprest-dev
}

install_json_schema_validator() {
  # nlohmann_json_schema_validator (pboettch/json-schema-validator) は
  # Ubuntu 24.04標準リポジトリに存在しないため、ソースからビルド・インストールする。
  # nmos-cppのCMakeLists(cmake/NmosCppDependencies.cmake)がfind_packageで要求する。
  log "nlohmann_json_schema_validator をソースから取得・ビルド"
  mkdir -p "${BUILD_DIR}"
  cd "${BUILD_DIR}"
  if [[ ! -d json-schema-validator ]]; then
    git clone --depth 1 https://github.com/pboettch/json-schema-validator.git
  fi
  cd json-schema-validator
  mkdir -p build
  cd build
  cmake .. -DCMAKE_BUILD_TYPE=Release -DJSON_VALIDATOR_BUILD_TESTS=OFF
  cmake --build . -j"$(nproc)"
  cmake --install .
  ldconfig
}

install_jwt_cpp() {
  # jwt-cpp (Thalhammer/jwt-cpp) はヘッダオンリーライブラリだが、Ubuntu 24.04
  # 標準リポジトリには存在せず、nmos-cppのCMakeLists(cmake/NmosCppDependencies.cmake)
  # がfind_package(jwt-cpp)を要求するため、cmake configを含めてインストールする。
  log "jwt-cpp をソースから取得・インストール(ヘッダオンリー)"
  mkdir -p "${BUILD_DIR}"
  cd "${BUILD_DIR}"
  if [[ ! -d jwt-cpp ]]; then
    git clone --depth 1 https://github.com/Thalhammer/jwt-cpp.git
  fi
  cd jwt-cpp
  mkdir -p build
  cd build
  cmake .. -DCMAKE_BUILD_TYPE=Release -DJWT_BUILD_EXAMPLES=OFF
  cmake --install .
}

fetch_source() {
  mkdir -p "${BUILD_DIR}"
  cd "${BUILD_DIR}"
  if [[ ! -d nmos-cpp ]]; then
    git clone https://github.com/sony/nmos-cpp.git
  fi
  cd nmos-cpp
  git fetch --all --tags
  git checkout "${NMOS_CPP_REF}"
}

integrate_custom_node_implementation() {
  log "MultiViewer固有のnode_implementationを組み込み"
  local target="${BUILD_DIR}/nmos-cpp/Development/nmos-cpp-node/node_implementation.cpp"
  if [[ -f "${target}" ]]; then
    cp "${target}" "${target}.orig.bak"
  fi
  # nmos-cppのサンプルnode実装を、本プロジェクト固有の実装(4映像+1音声Receiver
  # のみを公開し、Senderを一切生成しない)で置き換える。
  # 実際の統合には、multiviewer_node_implementation.cpp内の関数シグネチャを
  # 対象nmos-cppバージョンのnode_implementation.hに合わせて調整する必要がある
  # (nmos-cppのバージョンによりシグネチャが変わるため、ビルド時に要確認)。
  cp "${HERE}/../node_implementation/multiviewer_node_implementation.cpp" "${target}"
  log "置き換え完了。オリジナルは ${target}.orig.bak に退避"
}

build() {
  cd "${BUILD_DIR}/nmos-cpp/Development"
  mkdir -p build
  cd build
  cmake .. -DCMAKE_BUILD_TYPE=Release
  cmake --build . --target nmos-cpp-node -j"$(nproc)"
  log "ビルド完了: ${BUILD_DIR}/nmos-cpp/Development/build/nmos-cpp-node/nmos-cpp-node"
}

main() {
  require_root
  install_deps
  install_json_schema_validator
  install_jwt_cpp
  fetch_source
  integrate_custom_node_implementation
  build
}

main "$@"
