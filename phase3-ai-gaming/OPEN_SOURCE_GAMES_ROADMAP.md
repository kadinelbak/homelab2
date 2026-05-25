# Open Source Games Roadmap

This roadmap is for building a large, ad-free game catalog in your homelab while keeping legal/license risk low and UX quality high.

## Goals

- Host a broad catalog of high-quality browser games.
- Prefer well-maintained open-source upstream projects over custom one-off builds.
- Keep everything mobile-friendly and tailscale/port access only.
- Apply small, local UX revisions without forking too much.

## Curation Rules

Use these rules before integrating any game:

1. License must be explicit and acceptable (MIT, Apache-2.0, BSD, MPL-2.0, GPL/AGPL if you accept those obligations).
2. Project should show recent activity (prefer updates in last 12-18 months).
3. Build/deploy process must be reproducible.
4. Mobile usability must be acceptable or fixable with small overrides.
5. Track source, license, and local modifications in a NOTICE file per game.

## Current Status

- Running now: Sudoku (upstream Super Sudoku, locally customized).
- Running now: local custom Solitaire, Hearts, Memory (starter implementations).

## Vetted Candidate Pool

### Strong picks (good next integrations)

1. Checkers / Draughts
- Repo: https://github.com/shubhendusaurabh/draughts.js
- License: MPL-2.0
- Notes: practical, browser-oriented, lighter than full lidraughts stack.

2. Crossword
- Repo: https://github.com/Piterden/vue-crossword
- License: MIT
- Notes: active and suitable for browser deployment.

3. Crossword tooling / rendering alternative
- Repo: https://github.com/viresh-ratnakar/exolve
- License: MIT
- Notes: robust crossword engine ecosystem.

4. Word search
- Repo: https://github.com/lizhineng/word-search-game
- License: MIT
- Notes: clearer licensing than many alternatives.

### Possible but with caveats

1. Solitaire
- Repo: https://github.com/gcedo/react-solitaire
- License: MIT
- Caveat: older webpack toolchain currently fails clean build on modern npm/webpack-cli without patching.

2. Hearts
- Repo: https://github.com/yyjhao/html5-hearts
- License metadata: NOASSERTION
- Caveat: license clarity needed before direct reuse.

3. Full checkers platform
- Repo: https://github.com/RoepStoep/lidraughts
- License: AGPL-3.0
- Caveat: much heavier deployment and licensing obligations.

## Integration Strategy

### Phase A (quick wins)

1. Add Checkers from draughts.js.
2. Add Crossword from vue-crossword.
3. Add Word Search from lizhineng/word-search-game.

### Phase B (quality upgrades)

1. Replace local Solitaire with upstream-based version after build pipeline patching or selecting a newer alternative.
2. Replace local Hearts after selecting a license-clear project.

### Phase C (catalog scale)

1. Add a game metadata manifest (title, source repo, license, mobile score, status).
2. Auto-generate the homepage catalog from that manifest.
3. Add per-game quality checklist and update cadence.

## Per-game directory conventions

For each imported game:

- games/<slug>/
- games/<slug>/NOTICE.txt
- games/<slug>/LICENSE.<project>

NOTICE should include:

- Source repo URL
- Upstream license
- Date/version imported
- Local modifications made

## Security and network model

- Keep services on tailscale/port-only model.
- Do not expose game service on public ingress.
- Use ACL groups for access control.
- Keep UFW non-tailscale deny rules where needed.

## Immediate Next Steps

1. Integrate Checkers as first upstream import.
2. Integrate Crossword as second upstream import.
3. Integrate Word Search as third upstream import.
4. Re-run mobile polish pass per integrated game.

