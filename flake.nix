{
  description = "Differential testing oracle for Solidity compilers (solc vs solang)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };

      # solang is not packaged in nixpkgs; use the upstream prebuilt binary.
      solang-bin = pkgs.stdenvNoCC.mkDerivation rec {
        pname = "solang";
        version = "0.3.5";
        src = pkgs.fetchurl {
          url = "https://github.com/hyperledger-solang/solang/releases/download/v${version}/solang-linux-x86-64";
          hash = "sha256-oJBkWdzAchzZitoxyQCJyEFKtPeBGHQpzBbV+O9/WfE=";
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
