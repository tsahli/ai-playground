Scanline logic consists of 4 parts. The parts are:

- Bill ID - not a scanline input, positions 1-4
- Check Digit #1, position 5
- Check Digit #2, position 6
- Input String - input to scanline #1, position 7-61

See the “**Full Scanline**” below for the detailed summary.

<aside>
👉 Sent on September 12th to Deluxe. If any updates are made, please make sure to verify and send updated spec to Deluxe!

</aside>

## Input String - 55 characters (starting at position 7 of Full Scanline)

### Example Case for Documentation

The example input string for this document we’ll use is `2300100091100911115156840112312201312300005347000000000`

### Structure of Input String

Bullets are parts of input string in sequential order

- Invoice date, 5 digits - “Julian” format
  - first two digits abbreviated year, last 3 are positional day of year e.g. December 31st, 2023 is `23365`. January 1st, 2024 is `24001`.
  - Using the scanline example above the value is January 1st, 2023 `23001`
- Lockbox number, 3 digits - always `000`
- UPDATED → Company number, 2 digits - always `91`
- Line of Business (LOB), 1 digit - always `1`
- UPDATED → Location number, 2 digits - always `00`
- LOBP, 1 digit - always `9`
- UPDATED → Policy Symbol, 2 digits -
  - `11` represents Toggle Auto policies migration to Toggle 21st (e.g. `TCXXXXXXXX)`
  - NEW —> `02` represents Toggle Auto policies already on Sure platform (e.g. `TAXXXXXXXX`)
  - The example above, the digit is `11` since it is a `TC` policy.
- Policy number (full), 10 digits - composed of 2 parts below

    <aside>
    ⚠️ Note that policy numbers contain letters and numbers. This attempts to coerce the existing policy number into a different, numerical only policy number.

    </aside>

  - Policy Number (partial), 8 digits - a conversion is performed using the following strategy with python functionality built into the standard library.
    - Drop off the first two letters of the policy e.g. `TC12345678` becomes `12345678`
    - Compute the md5 hash of the the 8 digit item. This will output a consistent 32 digit hexidecimal character (typically 128 bits)
    - Convert the hexidecimal string to decimal - e.g. a = 11, b = 12, etc. **Note: do this for the entire value and not 1 digit at a time (see example below).**
    - Grab the first 8 digits as a reproducible “finger print” of a policy number
    - Example:
      - Original `TC123ABC45` → `123ABC45` drop first two letters (e.g. policy symbol)
      - md5 hash of `123ABC45` is `56a266f3ca501014cace185e90bbc1b1`
      - `56a266f3ca501014cace185e90bbc1b1` converted to decimal (i.e. base 16 to base 10 integer) is `115156847849421232573059751680449167793`
      - The first 8 digits of that value are `11515684`
  - Policy Term, 2 digits - will be the term of the current policy number. First term will be `01` and increment by 1 up to a limit of `99`
  - The full example policy number is `1151568401`

- Policy Effective Date, 6 digits - policy’s current term start date in format of MMDDYY
  - The example uses `123122`
- Final Accept Date, 6 digits - current policy installment “due at” date + 10 days in format of MMDDYY
  - The example uses `013123`
- Minimum Amount Due, 8 digits - amount due converted to integer and padded with zeros to always be same length i.e. $53.74 → `00005374`, $120.01 → `00012001`
  - The example uses `00005347`
- Current Balance, 8 digits - always `00000000`
- State Code, 1 digit - always `0`

## Check Digit #1

Take the output of the 55 digit Input String and sum up each digit to get a total for check digit #1. Then, subtract from that total the last digit of the “coerced” policy number. The last digit of that number is Check Digit #1.

For example, summing up the 55 character input string by adding each digit to the sum, a total of `153` is produced. The coerced policy number is `11515684`, so the last digit of that is `4`. Check Digit #1 is the last digit of 153 - 4 which is `9` (153 - 4 = 149 → last digit is 9).

## Check Digit #2

Take the output of the 55 digit Input String, and grab a substring starting at position 15 to position 46. The resulting substring will be **32 digits** in length. For example, if the original input string is `2300100091100911115156840112312201312300005347000000000` then the substring will be `11115156840112312201312300005347`

Run the following algorithm on the substring:

- Loop through each digit tracking index starting at 0.
- UPDATED → If the index of the current loop is odd **_AND_ value of the digit > 0**, do the following:
  - Multiply the value of the digit at that index times 3 and subtract 1.
  - Take the first and last digit of that number. If the number is only 1 digit then use it as both first and last.
  - Add those two numbers together and add that the check digit #2 sum.
- UPDATED → If the index of the current loop is even (0,2,4,6…etc.) **_OR_ value of the digit == 0** (e.g. the `else` case) then add it to the check digit #2 sum as-is.
- Return the last digit of the check digit #2 sum
-

In the example the substring for check digit #2 is `11115156840112312201312300005347`.

- first loop is index 0, value of `1`. Index 0 is even, so add `1` to the sum for a total of also `1`
- second loops index is 1, value is again `1`. Index 1 is odd so do the following
  - (1 \* 3) - 1 = `2`
  - Take the first and last digit of `2`, repeat since only one digit.
  - Add the first and last digit together to get `4`.
  - Add this to the running sum which has a total of `5` (1 + 4)
- The final output of the check digit sum is `132`. The last digit of that is `2`

## Full Scanline

The full scanline is as follows

- Bill ID, 4 digits - comprised of the following
  - Policy Term number, 2 digits - same as input string, is the policy’s term number i.e. `01` for the first incrementing by 1 for each term.
  - Installment number, 2 digits - this is the number of installment starting at `01` and incrementing by 1 for each installment.
  - The example uses
- Check Digit #1, 1 digit - see above
- Check Digit #2, 1 digit - see above
- Full Input string for check digit #1, 55 digits - see above

The resulting string should be 61 characters, all numeric.
