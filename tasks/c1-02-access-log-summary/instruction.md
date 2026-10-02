In /app, summarise logs/access.log (combined log format) into out/summary.json, an object with:

- requests: the number of requests in the log
- status: an object mapping each status code, as a string, to its number of requests
- top_paths: the three most requested paths, most requested first, ties broken by path in
  ascending order. A path is the request target without its query string.
- bytes: total response bytes; a "-" size counts as 0

Do not modify logs/access.log.
