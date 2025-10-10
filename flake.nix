{
  description = "CRD extractor shell script with dependencies";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = nixpkgs.legacyPackages.${system};

        pythonWithPackages = pkgs.python3.withPackages (ps:
          with ps; [
            pyyaml
          ]);
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonWithPackages
            pkgs.kubectl
            pkgs.curl
            pkgs.bash
            pkgs.coreutils
            pkgs.findutils
            pkgs.gnused
          ];

          shellHook = ''
            echo "$(python3 --version)"
            echo "$(kubectl version --client)"
            echo "context: $(kubectl config current-context 2>/dev/null || echo '<no context>')"
          '';
        };
      }
    );
}
