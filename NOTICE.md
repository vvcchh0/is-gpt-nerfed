# Attribution and source provenance

This Windows port is derived from **[kiyoakii/is-gpt-nerfed](https://github.com/kiyoakii/is-gpt-nerfed)**,
created by kiyoakii and the is-gpt-nerfed contributors. It is an independent community port,
not an official OpenAI product. The original project name and Codex plugin identity are retained.

- Upstream baseline: `ff0d7c0c8fdc8713273b6570b1ada1838eaad84c` (0.5.3, 2026-09-29).
- Windows work: the `windows` branch of [vvcchh0/is-gpt-nerfed](https://github.com/vvcchh0/is-gpt-nerfed/tree/windows), starting 2026-10-08.
- The supplied `is-gpt-nerfed-main` archive matches that baseline after normalizing Git line endings.
- Local Windows checkout: `if-gpt-nerfed-main`. The folder name does not rename the upstream plugin.
- Original MIT copyright and permission text remain in [LICENSE](LICENSE).
- ModelTrace bank, scorer and prompts: [xqy2006/ModelTrace](https://github.com/xqy2006/ModelTrace), MIT;
  exact source commit, model list and bank digest are retained in
  [provenance.json](plugin/assets/modeltrace/provenance.json) and its accompanying license.
- Original terminal picker: [IngoMeyer441/simple-term-menu](https://github.com/IngoMeyer441/simple-term-menu), MIT;
  vendored license retained. Windows uses a numbered picker instead.
- Random-number fingerprint inspiration: [hanlinwenyuan/hlwy-ai-checker](https://github.com/hanlinwenyuan/hlwy-ai-checker).
- Compiled Windows portable releases bundle the official [CPython 3.13.16 embeddable x64 runtime](https://www.python.org/downloads/release/python-31316/),
  from the Python Software Foundation and contributors. Its Python/third-party license text is retained
  in the distributed `runtime/LICENSE.txt`; fixed download provenance is recorded in the release manifest
  and [ADR 0003](docs/adr/0003-compiled-windows-distribution.md). Runtime binaries are not checked into Git.

The Windows port changes platform integration and presentation. It does not retrain the bank,
replace reference prompts, or claim independently measured attribution accuracy.
