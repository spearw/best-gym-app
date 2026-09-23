# GymTrainer Build Plan Review

The plan is solid overall. Here's everything I'd change, most important first:

- **Rename the `sessions` app.** It clashes with Django's built-in one, and Django won't start.
- **Use Postgres locally from the start.** The tag fields don't work on SQLite.
- **Give each program day a real date.** Nearly every "today" or "this week" query gets much simpler.
- **Decide whether a day can have two sessions.** Lots of lifters train morning and evening.
- **Don't store whether a day is done or missed.** Work it out from the session logs so the two can't disagree.
- **Link each logged set to what the coach prescribed.** Without that, you can't show "asked for X, did Y", and edits wipe out what was asked.
- **Store loads as numbers, not text.** Parsing "75%" out of a string on every read will bite you.
- **Check whether a prescription needs different loads per set.** Things like 70/75/80% are common and need their own table.
- **Plan now for complexes like "1+1" and timed work like "10 min".** The current set log can't hold either.
- **Keep 1RMs and bodyweight as history, not single fields on the athlete.** The charts need past values.
- **Let each exercise say which max its percentages come from.** Right now a front squat would be worked out from a back squat max.
- **Share one set of prescription fields between templates and programs.** They've already drifted apart, so applying a template loses data.
- **Add the few fields the plan uses but the tables don't list.** These are "published" on weeks, "active" on programs, and a table for undo.
- **Move the weekly focus note onto the week.** It's currently on the whole program.
- **Decide who fills in custom fields.** If it's the athlete, their answers need somewhere to live.
- **Link each check-in answer to its question as well as copying the text.** Otherwise rewording a question breaks the trend charts.
- **Put the coach on each message.** Otherwise a new coach would see the athlete's old conversation.
- **Stop notifications repeating.** As written, the nightly "program ending" alert fires every night, and athletes may want notifications too.
- **Work out whether someone's a coach or athlete from their profiles.** That lets a coach log their own training too.
- **Consider a gym as the owner instead of a coach.** It matters if coaches at one gym will ever share a library.
- **Store weights as exact decimals and round in the athlete's own unit.** kg and lb plates round differently.
- **Take the best estimated 1RM across all sets, not just the heaviest one.** A lighter set with more reps can score higher.
- **Pick a time zone approach early.** Every "today" depends on it.
- **The nightly cron job in the Render file has no database settings.** It'll fail as written.
- **Decide whether athletes need to log sets offline.** Gyms often have bad signal.
- **Recheck the phase order.** The library history strip in phase 3 needs session data from phase 4, and the text and table disagree on what phase 5 waits for.
