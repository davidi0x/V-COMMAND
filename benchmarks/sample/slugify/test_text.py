from text import slugify

assert slugify("Hello, World!") == "hello-world"
assert slugify("  A  B ") == "a-b"
assert slugify("C++ & Rust 2024") == "c-rust-2024"
assert slugify("") == ""
print("ok")
