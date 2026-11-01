from pages import paginate

items = list(range(1, 11))
assert paginate(items, 1, 3) == [1, 2, 3], paginate(items, 1, 3)
assert paginate(items, 4, 3) == [10]
assert paginate(items, 5, 3) == []
print("ok")
