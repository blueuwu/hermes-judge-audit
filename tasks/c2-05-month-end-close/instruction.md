Close September 2026 in /app:

1. Write out/2026-09-summary.csv with the header region,orders,revenue and one row per
   region, sorted by region. orders is the number of sale rows and revenue is the sum of
   qty * unit_price, to 2 decimal places, over every September 2026 file in sales/.
2. Move those September files into archive/2026-09/, unchanged.
3. Write archive/2026-09/MANIFEST.txt listing every archived file as `<sha256>  <filename>`
   (sha256sum format), sorted by filename.

Leave every other file in sales/ where it is.
