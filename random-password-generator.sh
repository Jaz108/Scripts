# Define character sets
SPECIALS='%*-_+'
ALPHANUM='A-Za-z0-9'

# Pick 1 special character
special_char=$(echo "$SPECIALS" | fold -w1 | gshuf | head -n1)
...
echo "$alnum_chars$special_char" | fold -w1 | gshuf | tr -d '\n'; echo


# Combine and shuffle
echo "$alnum_chars$special_char" | fold -w1 | shuf | tr -d '\n'; echo

