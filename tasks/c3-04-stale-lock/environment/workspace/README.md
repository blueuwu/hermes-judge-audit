# shop-frontend

Build with `bin/build.sh`. It writes `dist/app.bundle.js` and `dist/BUILD_INFO`.

Only one build runs at a time: `bin/build.sh` holds `build.lock`, which contains its pid,
and removes it on exit. A build that is killed can leave `build.lock` behind. Before
deleting a leftover lock, check that the pid in it is not running (`ps -p <pid>`).
