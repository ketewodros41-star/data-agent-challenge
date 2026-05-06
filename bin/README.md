# bin — Vendored Binaries

Executables that are not managed by `uv` and must travel with the repo.

| File | Purpose |
| --- | --- |
| `toolbox`     | Google MCP Toolbox launcher (wrapper) |
| `toolbox.bin` | The actual toolbox binary |

`scripts/setup_dab.sh` expects `bin/toolbox` to exist and be executable.

## Updating the toolbox binary

Download the latest release from [googleapis/genai-toolbox](https://github.com/googleapis/genai-toolbox/releases) for Linux x86_64 and drop it in as `bin/toolbox.bin` (preserve the `toolbox` wrapper). Make sure both are executable:

```bash
chmod +x bin/toolbox bin/toolbox.bin
```
