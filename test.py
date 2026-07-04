a = 23.234
my_name = 27
# print(37 + my_name)

ages_i_family = [1,5,6,30,32]
my_family = [{'name': 'Gary', "age": 32, "adult":True}, {'name': 'adina', "age": 30, "adult":True}, {'name': 'tirtza', "age": 6, "adult":False}, ['name',45,68]]

for person in my_family:
    if 'name' in person:
        print(person['name'])