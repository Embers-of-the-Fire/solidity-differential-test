{
  description = "Nix shell for solc vs solang differential testing";

  inputs = {
    nixpkgs.url = "https://github.com/NixOS/nixpkgs/archive/4bd9165a9165d7b5e33ae57f3eecbcb28fb231c9.tar.gz";
  };

  outputs =
    {
      self,
      nixpkgs,
    }:
    let
      supportedSystems = [
        "x86_64-linux"
      ];

      forAllSystems =
        f:
        nixpkgs.lib.genAttrs supportedSystems (
          system:
          f (
            import nixpkgs {
              inherit system;
            }
          )
        );
    in
    {
      packages = forAllSystems (
        pkgs:
        let
          solang = pkgs.stdenvNoCC.mkDerivation {
            pname = "solang";
            version = "0.3.4";

            src = pkgs.fetchurl {
              url = "https://github.com/hyperledger-solang/solang/releases/download/v0.3.4/solang-linux-x86-64";
              hash = "sha256-avZ7uf8i9TnC68n4s8xwlK15C/EEZtnM0i+gUCw6Bl0=";
            };

            dontUnpack = true;
            nativeBuildInputs = [ pkgs.autoPatchelfHook ];
            buildInputs = [
              pkgs.stdenv.cc.cc.lib
              pkgs.zlib
            ];

            installPhase = ''
              install -Dm755 "$src" "$out/bin/solang"
            '';
          };

          substrate-contracts-node = pkgs.stdenvNoCC.mkDerivation {
            pname = "substrate-contracts-node";
            version = "0.42.0";

            src = pkgs.fetchurl {
              url = "https://github.com/paritytech/substrate-contracts-node/releases/download/v0.42.0/substrate-contracts-node-linux.tar.gz";
              hash = "sha256-pjG06D3QXkvqzL13C+cJrEGRQYPUQxFsLk0kQWFZAmU=";
            };

            installPhase = ''
              install -Dm755 substrate-contracts-node "$out/bin/substrate-contracts-node"
            '';
          };
        in
        {
          inherit solang substrate-contracts-node;
          default = solang;
        }
      );

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [
            bashInteractive
            cargo
            clang
            coreutils
            diffutils
            findutils
            gawk
            go-ethereum
            gnugrep
            jq
            llvmPackages.libclang
            nixfmt
            nushell
            openssl
            pkg-config
            python3
            ruff
            rustc
            shellcheck
            shfmt
            self.packages.${pkgs.system}.solang
            self.packages.${pkgs.system}.substrate-contracts-node
            solc
            statix
            wasm-tools
          ];

          shellHook = ''
            mkdir -p working/cases working/out working/repro working/scripts
            printf '%s\n' "Development shell ready. Work under ./working"
          '';
        };
      });
    };
}
