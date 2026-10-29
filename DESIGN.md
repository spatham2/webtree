# Web Tree v1.0: A constellation GUI for branching Claude sessions

- **Status:** draft, nothing built.
- **Scope:** local-only tool over existing Claude Code state. No changes to Claude Code itself.
- **Frontends:** a web GUI (stylistic, full 8-bit look) and a CLI (terminal, functional). Both run on one shared core.

## Problem

- Claude sessions are a flat list (`/resume`). Forks and related work have no visible lineage.
- Shared context (config, memory) is invisible. It is hard to tell which sessions ran under which memory.
- Forking is cheap but unrecorded: speculative branches clutter the list, or are never created.

## Concepts

| Term | Meaning | Backing data |
|---|---|---|
| Sun | One global root. The user's preferences for how sessions should answer, in two layers: overall and per project. | Overall: `~/.claude/settings.json`, `~/.claude/CLAUDE.md` (if present). Project: `~/.claude/projects/<project>/memory/` (`MEMORY.md` plus memory files such as `sol`, `cvs`, `ior` shorthands), repo `CLAUDE.md` |
| Planet | One instantiated conversation. Holds that session's context. | Session transcript `~/.claude/projects/<project>/<session-id>.jsonl` |
| Branch | Edge from parent (sun or planet) to child planet. | Tree metadata (below) |
| Cloud | Staged, not-yet-created conversation. Fuzzy node. | Tree metadata only; no transcript |
| Constellation | Background. Purely visual. | n/a |
| Cluster | Group of 10+ planets in one project with related topic names, named in 5-10 words. | Tree metadata |
| Context pull | Drag a planet or cluster into the active session as context. | Pull file, generated at pull time |
| Outside reviewer | Fresh agent that reviews the active session's problem. Not a context source. | Reviewer run record |
| Drop bin | Side screen holding sessions started outside the GUI until placed. | Tree metadata |

## Frontends

- Two frontends over one shared core. The core owns `tree.json`, pull files, branch methods, and reading `~/.claude`.
- Both frontends have the same features and write the same `tree.json`. They differ only in presentation and input.
- The web GUI has more design freedom (pixels, sprites, free animation), so it carries the stylistic look. The CLI is limited to character cells, so it favors speed and clarity.

| Aspect | Web GUI | CLI |
|---|---|---|
| Purpose | Explore and arrange the constellation | Fast lookup and actions from the terminal |
| Main view | 2D night sky, radial layout from the sun, pan and zoom | Collapsible tree list (sun at top, planets indented), like `/resume` |
| Look | Full 8-bit style: sprites, 16-color palette, dithered clouds | Terminal 16 colors. Planets as colored glyphs or names, clouds dimmed or italic |
| Planet size tier | Mars / Earth / Jupiter sprite | Tier marker beside the name (e.g. `●` `◉` `⬤`) plus context % |
| Clusters | One node zoomed out; zoom in to open | Collapsible group row with its 5-10 word name |
| Reviewers | Satellites orbiting the planet | Child rows marked as reviewers |
| Pull edges | Drawn lines between planets | Listed in the side panel of source and target |
| Drop bin | Strip below the sky; drag onto a parent | Separate pane; pick a session, then pick a parent from the suggested list |
| Placement, pulls | Drag and drop | Keyboard: select source, press action key, select target |
| Hover info | Mouse hover popup | Shown in the side panel for the highlighted row (mouse hover also works) |
| Side panel | Right side, on select | Right pane, follows the highlight |
| Open in terminal | Copies the `claude --resume` command | Runs it directly (or in a new tmux pane) |

### CLI feel
- Target the responsiveness of Claude Code's `/resume` screen: windowed list, only visible rows drawn, highlight moves redraw only changed lines, no animation delay.
- Keyboard first (arrows / `j` `k`, `/` to filter, Enter to open), mouse wheel and click supported.
- No 2D map in the CLI in v1. Character cells make free panning step one cell at a time.

## Behavior

### Tree
- The single global sun is always the root. Top-level planets branch directly off it.
- Planet children are forks or follow-ups of that planet.
- Selecting a node opens a side panel: summary, parent, created time, cwd/branch, open-in-terminal command.

### Sun node
- Opening the sun shows two layers:

| Layer | Applies to | Contents |
|---|---|---|
| Overall | Every session | `~/.claude/settings.json`, `~/.claude/CLAUDE.md` (if present) |
| Project | Sessions in that project only | One section per project: `memory/MEMORY.md`, each memory file, repo `CLAUDE.md` |

- Memory stays per repository. The sun does not copy or promote project memory to overall.
- Selecting a planet highlights the overall layer and that planet's project section, i.e. exactly what that session loads.
- Read-only in v1. Editing stays in the user's editor.
- Each planet records a snapshot hash of the overall layer plus its project section at creation, so drift ("this session predates memory X") is visible.

### Branch methods
- Each branch method is a plugin with one contract: given a parent planet, start a new session and return nothing (the session id is found by the step below).
- v1 ships only `fork`: `claude --resume <parent-id> --fork-session`.
- Other methods (e.g. new session seeded with a summary of the parent) are out of scope. The `method` field and plugin contract exist so they can be added later without a data model change.

### Staging (cloud) a branch
1. User picks a planet and chooses a branch method. A cloud node appears under it.
2. The cloud stores: parent planet, branch method, optional name/intent note, color palette.
3. No process starts and no transcript is written. Clouds can be renamed or discarded freely.

### Instantiating
1. Click a cloud, choose "Instantiate conversation". Pick the planet's color palette (see 8-bit look).
2. The tool lists `~/.claude/projects/<project>/`, runs the branch method, then lists the directory again.
3. The new `<session-id>.jsonl` that appeared is the new session. Its id is recorded on the node.
4. The cloud becomes a solid planet, permanent in the tree and available as a parent for further branches.
5. Failure (no new file, or more than one) leaves the node a cloud with the error shown. Nothing half-instantiated.

### Sessions started outside the GUI
- New transcripts not in `tree.json` go to the drop bin, a side screen next to the tree.
- Hovering a binned session shows its summary. Drag it from the bin onto a parent (sun or planet) to place it.
- Each binned session shows a ranked list of suggested parents. Ranking uses the same project and related topic names, then nearest creation time.
- Placement is always the user's action. Suggestions never auto-place.

## Feature: clusters

### Problem
- Parallel and branching sessions on one project pile up. Finding one gets hard.

### Behavior
- Clusters live inside one project. A cluster is a group of related sub-projects within that project.
- A cluster forms when 10+ planets in the same project have related topic names. Similarity uses topic names only, not model judgment of the whole transcript.
- Each cluster has a name of 5-10 words summarizing what all its sessions are about.
- Zoomed out, a cluster renders as one node. Pan to it and zoom in to open it and show its member planets.
- Membership is proposed automatically. The user can accept, move planets between clusters, or rename.
- A planet belongs to at most one cluster.

## Feature: pulling in context

### Problem
- Useful context lives in another session (e.g. a UI built elsewhere, needed in an electrical engineering session).

### Behavior
- Select a planet and drag it onto the active session to pull its context in.
- "Context" means the source's context window. A summary is the default. The full transcript is an option.
- The user picks the amount at pull time:

| Level | Content added |
|---|---|
| Full | The source's full transcript, on top of the active session |
| Compacted (default) | A summary of the source's context window |
| Extra-compacted | A shorter summary than above |

- Selecting a cluster pulls a brief summary of each member as context. The user can then pull a specific member at a higher level for more detail.
- Pulls are recorded as edges from source to target, distinct from parent-child branches. The source is unchanged.

### Delivery
- Delivered into the live session as a prompt.
- v1 mechanism: write the pulled content to a pull file, `~/.claude/webtree/pulls/<pull-id>.md`, and copy a prompt referencing it (`@<path>`) to the clipboard for the user to paste.
- If Claude Code has a built-in way to send one session's context to another, use it instead of the file. Not yet verified (see open questions).

## Feature: outside reviewers

### Problem
- A large context window makes the model less effective. It resists other perspectives and stops generating new ideas.

### Behavior
- The user attaches an outside reviewer to the active session. The reviewer is either an agent that is not from the current context window, or a brand-new session.
- The reviewer attacks the problem itself and returns its review. It is not just a context donor.
- This is separate from context pull. A pull gives the active session more context. A reviewer does the reviewing with its own.
- The review result lands in the active session as a message. The reviewer's own context does not.
- Several reviewers can run on one planet at once. Each returns its own review.
- Reviewers are shown on the tree as satellites of the reviewed planet.

## Feature: session size on hover

- Hovering a planet shows two numbers for that session only:
  - Lifetime token total of the session.
  - Size of the transcript file on disk (e.g. 80 MB).
- Both are read at hover time, not stored in `tree.json`.
- Clouds show nothing (no transcript yet).

## Feature: planet size by context window

### Problem
- A large context window degrades the session. There is no visual cue that it is time to cut down or split.

### Behavior
- Planet size grows with the session's current context window, in tiers:

| Tier | Planet | Range (% of model context window) |
|---|---|---|
| 1 | Mars | < 25% |
| 2 | Earth | 25-60% |
| 3 | Jupiter | > 60% |

- Size uses the current context window, not lifetime tokens, so compaction shrinks the planet.
- Tier changes are automatic. Planet size is one signal. Other automatic signals (e.g. a badge at Jupiter) can be added. Each signal can be turned on or off by the user.
- Every planet has a "Split" action, at any tier. Splitting is always the user's choice and never runs automatically.

## Feature: 8-bit look and per-session color

- Web GUI only. The CLI uses the terminal's 16 colors and maps each palette to its nearest terminal color.

### Visual style
- 8-bit night sky with 8-bit planets: pixel-art sprites, no anti-aliasing, integer scaling.
- One master palette of 16 colors for the whole GUI.
- Clouds are drawn with dithering instead of blur, to stay within the palette.
- Each planet tier (Mars, Earth, Jupiter) has its own sprite.

### Color palettes
- Each planet sprite is drawn in a palette: a small set of colors taken from the master palette.
- Each tier has a default palette and several alternatives:

| Planet | Default | Example alternatives |
|---|---|---|
| Earth | green + blue | red + purple, brown + orange |
| Mars | (to be set) | (to be set) |
| Jupiter | (to be set) | (to be set) |

- The user picks a palette when instantiating a cloud. Default: the parent planet's palette, else the tier default.
- The palette can be changed later from the side panel.

## Data model

Stored in `~/.claude/webtree/tree.json`, separate from Claude's own files:

```json
{
  "nodes": {
    "<node-id>": {
      "kind": "planet | cloud | binned",
      "session_id": "<id or null while cloud>",
      "parent": "<node-id, 'sun', or null while binned>",
      "method": "fork",
      "note": "",
      "sun_snapshot": "<hash>",
      "project": "<project dir name>",
      "cluster": "<cluster-id or null>",
      "palette": "<palette-id>",
      "created": "<iso8601>"
    }
  },
  "clusters": {
    "<cluster-id>": { "project": "<project dir name>", "name": "<5-10 words>", "members": ["<node-id>"] }
  },
  "pulls": [
    { "source": "<node-id or cluster-id>", "target": "<node-id>", "level": "full | compacted | extra_compacted | cluster_summary", "file": "<pull file path>" }
  ],
  "reviews": [
    { "target": "<node-id>", "reviewer": "<node-id or 'agent'>", "created": "<iso8601>" }
  ],
  "signals": { "planet_size": true }
}
```

- Planets reference transcripts; they never copy or modify them.
- The tree can be rebuilt partially from transcripts alone (all sessions land in the drop bin), so losing `tree.json` loses lineage only.

## Architecture

- Shared core library: reads `~/.claude`, owns `tree.json` and pull files, runs branch methods (shells out to `claude`). Both frontends call it.
- Web GUI: small local backend wrapping the core, plus a browser frontend. Canvas with pixel-art rendering, radial layout from the sun. Clouds are dithered; planets are solid sprites. Binds to localhost only.
- CLI: terminal UI calling the core directly, no server. Candidate framework: Textual (Python), for its list, tree, side-panel, and mouse support.
- The core is read-only against `~/.claude` except via the `claude` CLI and its own `~/.claude/webtree/` directory.
- No transcript data leaves the machine.

## Non-goals (v1)

- Branch methods other than fork (plugin contract only).
- Editing sun files in the GUI.
- Merging branches.
- Multi-user or remote sharing.
- Running or streaming conversations inside the GUI.

## Decisions

| Question | Decision |
|---|---|
| How to find a new session's id | List the project directory before and after; the new `.jsonl` is the session |
| Branch methods other than fork | Needed later. Plugin contract now, out of v1 scope |
| Sun scope | One global sun showing two layers: overall memory and per-project memory |
| Memory location | Stays per repository; not promoted to overall |
| Sessions started outside the GUI | Drop bin side screen, with suggested parents |
| What "context" means | The context window. Summary by default, full transcript as an option |
| Clustering method | Topic names, within one project |
| Pull delivery | As a prompt. Pull file now, built-in mechanism if one exists |
| Parallel reviewers | Yes |
| Hover count | Lifetime tokens and transcript file size, for that session only |
| Tier ranges | < 25%, 25-60%, > 60% |
| Split | Available on every planet; always the user's choice |
| Size signals | Automatic, each can be turned on or off by the user |
| Colors | Multiple palettes per planet; user picks |
| Frontends | Web GUI (stylistic) and CLI (functional) over one shared core and one `tree.json` |

## Open questions

### Still open from earlier
- Can a cluster form below 10 planets if the user asks for it?
- Are compacted and extra-compacted summaries generated once and cached, or on each pull?
- Reviewer input: what does a reviewer see? The active session's context, a problem statement only, or a user-chosen slice? Seeing none is the point, but it needs something to review.
- Which 16-color master palette (e.g. PICO-8, a custom one)? Does it need a colorblind-safe check?
- Do clusters, reviewers (satellites), pull edges, and the drop bin get their own 8-bit sprites, and how are they told apart?

### New
- What counts as a "project" for clusters and project memory? Claude Code makes a directory per cwd, so each git worktree (e.g. `~/devel/monorepo-*`) is a separate project with its own (empty) memory. Should worktrees of one repo show as one project section in the sun?
- Where do topic names come from: the session name (e.g. `/rename Build_Webtree`), the first prompt, or a generated title? What happens to unnamed sessions?
- Session id by directory diff can be ambiguous if another session starts in the same project at the same moment. Is "fail and stay a cloud" acceptable, or should it match on the fork's first message?
- Is there a built-in Claude Code way to send one session's context into another live session? If not, is copy-to-clipboard of an `@<pull file>` prompt acceptable for v1?
- What does "Split" produce? Two children each seeded with part of the parent's context needs a non-fork branch method, which is out of v1 scope. Should split be a v1 exception, or wait for branch plugins?
- Lifetime token total: count input + output only, or include cache reads? Cache reads can make the total many times larger than what was actually written.
- How is the current context window % measured: from the last message's usage record (input + cache tokens)? Does it hold after `/compact`?
- When a planet changes tier (Earth to Jupiter), does its palette carry over (red + purple Earth becomes red + purple Jupiter)?
- Summaries (for pulls, drop bin hover, cluster names) cost model calls. When are they generated, and is that cost acceptable?
- If the web GUI and CLI run at the same time, how are concurrent writes to `tree.json` handled (file lock, or reload on change)?
- Which frontend ships first?
- Should the CLI get an optional 2D map view later (braille-drawn sky), or stay list-only?

## Milestones

Milestones 1-8 are built in the shared core and in both frontends. Milestone 9 is web GUI only.

1. Read-only tree: sun plus all existing sessions in the drop bin.
2. Placement: drop bin, suggested parents, drag to place.
3. Lineage: fork through the GUI, session id by directory diff, sun snapshots.
4. Clouds and instantiation; branch method plugin contract.
5. Clusters: topic-name grouping per project, naming, zoom-to-open.
6. Context pull at all levels, for planets and clusters; pull files.
7. Outside reviewers, several per planet.
8. Session size on hover; planet size tiers; split action; signal toggles.
9. 8-bit style: master palette, sprites, dithered clouds, per-planet palettes.
