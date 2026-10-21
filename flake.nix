{
  description = "Differential testing oracle for Solidity compilers (solc vs solang)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };

      # solang is not packaged in nixpkgs; use the upstream prebuilt binaries.
      # mkSolang is parameterized over versions (T2.2): the 0.3.x line is
      # exposed as packages.solang_0_3_0 … solang_0_3_5 for multi-version
      # oracle runs via ORACLE_SOLANG_BIN; the devShell keeps the latest.
      mkSolang =
        version: hash:
        pkgs.stdenvNoCC.mkDerivation {
          pname = "solang";
          inherit version;
          src = pkgs.fetchurl {
            url = "https://github.com/hyperledger-solang/solang/releases/download/v${version}/solang-linux-x86-64";
            inherit hash;
          };
          dontUnpack = true;
          nativeBuildInputs = [ pkgs.autoPatchelfHook ];
          buildInputs = [
            pkgs.stdenv.cc.cc.lib
            pkgs.zlib
          ];
          installPhase = ''
            install -Dm755 $src $out/bin/solang
          '';
          meta.mainProgram = "solang";
        };

      solang-bin = mkSolang "0.3.5" "sha256-oJBkWdzAchzZitoxyQCJyEFKtPeBGHQpzBbV+O9/WfE=";
      solang_0_3_0 = mkSolang "0.3.0" "sha256-kt+Obk25HqVufCdmnt7KkSh+AS4PBCsNd+1y6yGXj58=";
      solang_0_3_1 = mkSolang "0.3.1" "sha256-SCHGk31RNrt8Or99k9Y7mNqdVCapBp2wknj6mrN+cHc=";
      solang_0_3_2 = mkSolang "0.3.2" "sha256-aUgc0cXyiyBvzye3wKLFCsJDevVPzwyD3588zn2Qtd4=";
      solang_0_3_3 = mkSolang "0.3.3" "sha256-ETFmzAyflgZd7Nxsw3b+BNe6Fw/NQ3zPGo5GCQMCF5s=";
      solang_0_3_4 = mkSolang "0.3.4" "sha256-avZ7uf8i9TnC68n4s8xwlK15C/EEZtnM0i+gUCw6Bl0=";

      # substrate-contracts-node is not packaged in nixpkgs; use the upstream
      # prebuilt binary (Polkadot contracts chain used to run solang output).
      substrate-contracts-node = pkgs.stdenvNoCC.mkDerivation rec {
        pname = "substrate-contracts-node";
        version = "0.42.0";
        src = pkgs.fetchurl {
          url = "https://github.com/paritytech/substrate-contracts-node/releases/download/v${version}/substrate-contracts-node-linux.tar.gz";
          hash = "sha256-pjG06D3QXkvqzL13C+cJrEGRQYPUQxFsLk0kQWFZAmU=";
        };
        sourceRoot = ".";
        nativeBuildInputs = [ pkgs.autoPatchelfHook ];
        buildInputs = [ pkgs.stdenv.cc.cc.lib ];
        installPhase = ''
          install -Dm755 substrate-contracts-node-linux/substrate-contracts-node $out/bin/substrate-contracts-node
        '';
        meta.mainProgram = "substrate-contracts-node";
      };
    in
    {
      packages.${system} = {
        inherit solang-bin substrate-contracts-node;
        inherit solang_0_3_0 solang_0_3_1 solang_0_3_2 solang_0_3_3 solang_0_3_4;
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          pkgs.solc
          pkgs.foundry # provides anvil (EVM chain for solc output)
          solang-bin
          substrate-contracts-node
          pkgs.uv
          pkgs.python3
          pkgs.typst # compiles reports/*.typ (progress reports)
        ];

        shellHook = ''
          echo "solidity-diff-test devshell"
          echo "  solc:                      $(solc --version | tail -1)"
          echo "  anvil:                     $(anvil --version | head -1)"
          echo "  solang:                    $(solang --version)"
          echo "  substrate-contracts-node:  $(substrate-contracts-node --version)"
        '';
      };
    };
}
