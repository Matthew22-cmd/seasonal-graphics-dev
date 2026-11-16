# Publishing: the development copy and the operational site

There are TWO sites and they are two repositories:

| | repository | address |
|---|---|---|
| **dev** | `Matthew22-cmd/seasonal-graphics-dev` | `https://matthew22-cmd.github.io/seasonal-graphics-dev/` |
| **operational** | `massachusettswx-weather/seasonal-graphics` | `https://massachusettswx-weather.github.io/seasonal-graphics/` |

```bash
./push_to_github.sh            # the DEVELOPMENT site (the default)
./push_to_github.sh --prod     # the OPERATIONAL site
```

**A change is never automatically put on the operational site.**  It goes to
the development copy, where it can be anything, and it reaches the
operational site only when `--prod` is asked for.

## Why the build has to be told which target it is making

The site's links are ABSOLUTE (the nav tabs, the crumbs, the canonical
tag, the title link), because a relative `href="index.html"` made the
browser resolve it to `.../index.html` and that is what popped up in the
reader's link preview.  An absolute link, though, is only right for the
site that is actually being published - a dev build that links to the
operational site sends the reader to the wrong place, and its canonical
tag would point at the operational copy.

So `build_site.py` takes the target from the environment:

| variable | meaning |
|---|---|
| `SITE_URL` | the site's base URL |
| `SITE_REPO_URL` | the repository the "GitHub" link goes to |
| `SITE_DEV=1` | mark the build as the development copy |

and `push_to_github.sh` sets all three before it builds.  The build runs
**before** the commit, so the commit carries the right copy.

The development copy is marked "DEVELOPMENT COPY" in the header line and
in the browser tab, so nobody mistakes it for the live site.  The title
carries plain text (a `<title>` may not hold markup); the header line
carries the bold version.

## The README follows the target too

The README's link is rewritten by PATTERN, not by a placeholder: the build
writes the README back, so a placeholder would be consumed by the first
build and the second one would have nothing to replace.

## The history is shared, and that is fine

Both repositories get the same commits; they differ only in the LAST
commit, which carries the build for that target.  The operational
repository therefore keeps the whole history (its old commits, the
development commits, and the promoting commit) and its Pages site always
serves the tip - the production build.  A promote is a fast-forward, so no
force is needed.

## What the token can and cannot do

The token belongs to `Matthew22-cmd`.  It can create the development
repository (under its own account) and it is a write collaborator on the
operational one.  It **cannot** create a repository under
`massachusettswx-weather` - that account's repositories have to be created
by hand.  If the development copy is wanted under the main account, create
`massachusettswx-weather/seasonal-graphics-dev` by hand, add the token
account as a collaborator, and point the script at it with
`GITHUB_DEV_OWNER=massachusettswx-weather`.
