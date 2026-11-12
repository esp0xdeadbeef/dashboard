{
  description = "tmux-dashboard: scripted multi-pane tmux orchestration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      eachSystem = f: nixpkgs.lib.genAttrs systems (system:
        f system nixpkgs.legacyPackages.${system});
    in
    {
      packages = eachSystem (system: pkgs:
        let
          # Pin the dependency set: libtmux removes APIs between minor
          # releases, and compat.py targets the 0.62.x surface
          # (Server.sessions.get / Session.active_pane / active_window).
          py = pkgs.python3.withPackages (ps: [
            ps.libtmux
            ps.tinydb
          ]);

          # main_tdashboard.py imports compat.py as a sibling module, so both
          # must live in the same directory in the store.
          src = pkgs.runCommand "tmux-dashboard-src" { } ''
            mkdir -p $out/lib/tmux-dashboard
            cp -L ${./main_tdashboard.py} $out/lib/tmux-dashboard/main_tdashboard.py
            cp -L ${./compat.py} $out/lib/tmux-dashboard/compat.py
            cp -L ${./remote.py} $out/lib/tmux-dashboard/remote.py
            cp -L ${./termstate.py} $out/lib/tmux-dashboard/termstate.py
            cp -L ${./prompts.py} $out/lib/tmux-dashboard/prompts.py
            cp -L ${./prompts.txt} $out/lib/tmux-dashboard/prompts.txt
            cp -rL ${./scripts} $out/lib/tmux-dashboard/scripts
            chmod -R u+w $out
            chmod +x $out/lib/tmux-dashboard/scripts/*.sh || true
          '';

          dashboard = pkgs.writeShellApplication {
            name = "tmux-dashboard";
            # ssh is needed only for --target HOST; it is cheap to include
            # and keeps the wrapper honest about what it can do.
            runtimeInputs = [ py pkgs.tmux pkgs.coreutils pkgs.openssh ];
            text = ''
              # Refuse root. A tmux server is per-user, so a root-run
              # dashboard attaches to a *different* server than the one you
              # are sitting in, and anything it creates is root-owned. No part
              # of this needs privilege.
              if [ "$(id -u)" -eq 0 ]; then
                echo "tmux-dashboard: refusing to run as root." >&2
                echo "tmux servers are per-user; run this as your normal user." >&2
                exit 2
              fi

              # TMUX_TMPDIR pointing at another user's socket is the other way
              # to end up on the wrong server.
              if [ -n "''${TMUX_TMPDIR:-}" ] && [ ! -O "''${TMUX_TMPDIR}" ]; then
                echo "tmux-dashboard: TMUX_TMPDIR=$TMUX_TMPDIR is not owned by you" >&2
                exit 2
              fi

              exec ${py}/bin/python3 ${src}/lib/tmux-dashboard/main_tdashboard.py "$@"
            '';
          };
        in
        rec {
          inherit dashboard;
          ci = pkgs.runCommand "tmux-dashboard-ci" {
            nativeBuildInputs = [ py pkgs.shellcheck pkgs.tmux pkgs.openssh ];
          } ''
            # The store is read-only and both compileall and unittest want to
            # write __pycache__, so work on a copy.
            cp -r ${./.} src
            cd src
            chmod -R u+w .
            ${py}/bin/python3 -m compileall -q main_tdashboard.py compat.py \
              remote.py termstate.py prompts.py
            ${py}/bin/python3 -m unittest test_detection test_remote
            # `scripts/*.sh` are NOT shell scripts: they are payloads typed
            # line-by-line into a pane by send_keys_to_pane (a shebang there
            # would be typed as a command, and $(tty) must expand in the
            # pane's own shell). shellcheck assumes a standalone script and
            # reports SC2148/SC2046 on them, so only lint real shell files --
            # ones that begin with a shebang.
            sh_files=$(grep -l '^#!' scripts/*.sh 2>/dev/null || true)
            if [ -n "$sh_files" ]; then shellcheck $sh_files; fi
            touch $out
          '';
          default = dashboard;
        });

      apps = eachSystem (system: pkgs: rec {
        dashboard = {
          type = "app";
          program = "${self.packages.${system}.dashboard}/bin/tmux-dashboard";
        };

        default = dashboard;
      });

      devShells = eachSystem (system: pkgs:
        let
          py = pkgs.python3.withPackages (ps: [ ps.libtmux ps.tinydb ps.pytest ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              py
              pkgs.tmux
              pkgs.shellcheck
              pkgs.python3Packages.pytest
            ];

            shellHook = ''
              # Keeps a root-owned tmux server from silently becoming the target.
              if [ "$(id -u)" -eq 0 ]; then
                echo "warning: you are root; tmux-dashboard will refuse to run." >&2
              fi

              echo "tmux-dashboard dev shell"
              echo "  tmux-dashboard -i scripts --session-file scripts/1_session.py"
              echo "  tmux-dashboard --check --target HOST   # can I drive HOST?"
              echo "  pytest -q"
            '';
          };
        });

      formatter = eachSystem (system: pkgs: pkgs.nixfmt);

      # Expose the test suite as a check, so `nix flake check` actually runs
      # it. Without this, `check --no-build` only proves the outputs evaluate
      # and the tests are only run if someone happens to know about .#ci.
      checks = eachSystem (system: pkgs: {
        inherit (self.packages.${system}) ci;
        # `nix flake check` expects every check to be a derivation; the
        # package build is the cheapest proof that the wrapped script and its
        # Python environment are intact.
        dashboard = self.packages.${system}.dashboard;
        default = self.packages.${system}.ci;
      });
    };
}
