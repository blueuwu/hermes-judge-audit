# Dependency security

- `advisories.json`: the advisories that apply to our dependencies. `affected` is a
  comma-separated version range (all parts must hold); `fixed_in` is the first fixed
  release.
- `index.txt`: the versions available on the internal package mirror, one package per
  line. Only these versions can be installed.
