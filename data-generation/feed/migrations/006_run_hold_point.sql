-- The start point a seed-recording run holds at; demo control's capture checks it.
ALTER TABLE runs ADD COLUMN hold_point text;
