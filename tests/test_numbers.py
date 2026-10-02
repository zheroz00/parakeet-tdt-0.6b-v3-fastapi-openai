import pytest

from text_cleanup.numbers import convert_numbers


def converted(text):
    return convert_numbers(text)[0]


@pytest.mark.parametrize("spoken, written", [
    # decimals
    ("zero point one five millimeters", "0.15 millimeters"),
    ("four point two volts", "4.2 volts"),
    ("zero point one zero millimeters", "0.10 millimeters"),
    ("thirty eight point three tests", "38.3 tests"),
    ("three point twenty five", "3.25"),
    # plain numbers, units kept as spoken
    ("twenty four volts and thirty seven percent", "24 volts and 37 percent"),
    ("two seconds, two options", "2 seconds, 2 options"),
    ("wait thirty seconds", "wait 30 seconds"),
    ("one hundred ninety seven millimeters", "197 millimeters"),
    ("one hundred percent", "100 percent"),
    ("two thousand twenty six", "2026"),
    ("thirty-two bits", "32 bits"),
    ("Windows ten", "Windows 10"),
    ("Two options here.", "2 options here."),
    ("TWENTY FOUR volts", "24 volts"),
    ("four  point\ntwo", "4.2"),
    # numbers spoken in chunks
    ("a four seventy cap", "a 470 cap"),
    ("an eighteen six fifty cell", "an 18650 cell"),
    ("fifty six hundred", "5600"),
    ("one ninety seven", "197"),
    ("five six seven eight", "5678"),
    ("thirty-six zero eight", "3608"),
    # "and" after hundred/thousand belongs to the number
    ("one hundred and fifty", "150"),
    ("two thousand and five", "2005"),
    ("three hundred and twenty six", "326"),
    ("three and a half inches", "3 and a half inches"),
    ("one hundred and one hundred", "100 and 100"),
    ("three thousand and five hundred", "3500"),
    ("two hundred and fifty thousand", "250000"),
    # fractions
    ("one eighth of the way", "1/8 of the way"),
    ("a three sixteenth inch bit", "a 3/16 inch bit"),
    ("a one thirty second inch bit", "a 1/32 inch bit"),
    ("five thirty seconds", "5/32"),
    ("an eighth inch", "1/8 inch"),
    ("two thirds of it", "2/3 of it"),
    ("seven eighths", "7/8"),
    ("fifteen sixteenths", "15/16"),
    ("three quarters of it", "3/4 of it"),
    ("one quarter", "1/4"),
    ("a thirty second inch bit", "1/32 inch bit"),
    # hyphenated denominators, as the model often writes them
    ("a one thirty-second inch bit", "a 1/32 inch bit"),
    ("three thirty-second inch", "3/32 inch"),
    ("five sixty-fourths", "5/64"),
    ("three-quarters of it", "3/4 of it"),
    ("one-quarter of the way", "1/4 of the way"),
    ("seven-eighths", "7/8"),
    ("a thirty-second inch bit", "1/32 inch bit"),
    # not fractions: not in lowest terms, or a singular half/third/quarter
    ("I put two quarters in", "I put 2 quarters in"),
    ("two quarter-inch bolts", "2 quarter-inch bolts"),
    ("four eighths", "4 eighths"),
    # IPv4
    ("one ninety two dot one sixty eight dot one dot twenty", "192.168.1.20"),
    ("ten dot ten dot ten dot one fifty eight", "10.10.10.158"),
    ("zero dot zero dot zero dot zero", "0.0.0.0"),
    ("ten dot zero dot five", "10.0.5"),
])
def test_converts(spoken, written):
    assert converted(spoken) == written


@pytest.mark.parametrize("text", [
    "one of the things",
    "One more thing.",
    "the first one is better",
    "one second please",
    "at that point two things",
    "point being",
    "point two five zero spring",
    "the three dot menu",
    "the red dot in the corner",
    "ten dot five",
    "three hundred dot three hundred dot one dot one",
    "September twenty ninth",
    "on the twenty third",
    "twenty eighth",
    "a third option",
    "a half hour",
    "a hundred times",
    "one one-off",
    "five-volt rail",
    "Non-zero status",
    "someone, everyone, none, often",
    # hyphenated compounds stay whole
    "a sixty-four-bit build",
    "a twenty-one-year-old",
    "thirty-two-bit color",
    # "and" does not rescue a number that did not start
    "a hundred and fifty",
    # fraction look-alikes
    "two third party vendors",
    "one half-hour slot",
    "a thirty second timeout",
    "a thirty-second timeout",
    "the thirty-second time",
    "one-off",
    "two-quarters",
    "four thirty-seconds",
    "wait thirty-seconds",
    "two-quarter-inch bolts",
    "one-half-hour slot",
    "twenty-third",
])
def test_leaves_alone(text):
    assert converted(text) == text


@pytest.mark.parametrize("written, repaired", [
    ("a 132 inch bit", "a 1/32 inch bit"),
    ("a 1.32nd inch bit", "a 1/32 inch bit"),
    ("use a 1 32nd bit", "use a 1/32 bit"),
    ("3 16ths deep", "3/16 deep"),
    ("a 316 inch bit", "a 3/16 inch bit"),
    ("5 8ths", "5/8"),
    ("1564 inch", "15/64 inch"),
])
def test_repairs_fractions_the_model_wrote_in_digits(written, repaired):
    assert converted(written) == repaired


@pytest.mark.parametrize("text", [
    "an 18 inch board",
    "a 65 inch TV",
    "132 inches long",
    "a 232 inch run",
    "the 32nd time",
    "2.4 network",
])
def test_leaves_real_digit_numbers_alone(text):
    assert converted(text) == text


def test_reports_each_change():
    text, changes = convert_numbers("Set it to four point two volts, then two more.")
    assert text == "Set it to 4.2 volts, then 2 more."
    assert changes == [("four point two", "4.2"), ("two", "2")]


def test_punctuation_breaks_a_number():
    assert converted("one, two, three") == "one, 2, 3"


def test_empty_and_numberless_text():
    assert convert_numbers("") == ("", [])
    assert convert_numbers("Nothing to see here.") == ("Nothing to see here.", [])
