# names

Conventions of this package:

- `HTTPServerError` -> `http_server_error`, `userID` -> `user_id`, `parseJSON2Text` -> `parse_json2_text`.
- Strings that are already snake_case are returned unchanged; the empty string stays empty.
- A non-string argument raises `errors.ValidationError`.
