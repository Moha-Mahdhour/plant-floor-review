<!-- Per-chunk user message. Substitute {{...}} then send with the clip. -->

CHUNK: {{chunk_id}}
CLIP LENGTH: {{duration}} seconds  (playback is {{fps}} fps, so motion looks fast)
LOCAL TIME OF FIRST FRAME: {{clock_start}}  ({{weekday}})
Report all times as seconds from the first frame of THIS clip.

STATIONS (use these ids exactly):
{{station_list}}

STILL OPEN AT THE END OF THE PREVIOUS CHUNK:
{{open_events}}

If any of those are still happening in the first frames of this clip, re-report
them here with `continues_from_previous: true` so they can be stitched into one
continuous event.

Return JSON only, matching the schema.
