import copy
import math
import sys
from fractions import Fraction
from numbers import Number, Real
from typing import (ClassVar, Dict, Iterable, List, Literal, Optional, Tuple,
                    Type, Union)

import gmpy
import numpy as np
from memoization import cached

from histropy.utils.looping_list import LoopingList

from .errors import (EmptyStringException, IllegalBaseValueError,
                     IllegalFloatValueError, TooManySeparators, TypeMismatch)

"""
When performing tests on very precise numbers (For example sexagesimal with more than 7
fractional positions), avoid using floating number.
Use instead the Decimal BasedReal class.

>>> Sexagesimal(20.1, 10)
20 ; 06,00,00,00,00,00,00,00,14,16

>>> Sexagesimal(Decimal("20.1"), 10)
20 ; 06,00,00,00,00,00,00,00,00,00

"""

current_module = sys.modules[__name__]


class RadixBase:
    """
    A class representing a numeral system. A radix must be specified at each position,
    by specifying an integer list for the integer positions, and an integer list for the
    fractional positions.
    """

    # This dictionary records all the instantiated RadixBase objects
    name_to_base: ClassVar[Dict[str, "RadixBase"]] = {}

    def __init__(
        self,
        left: Iterable[int],
        right: Iterable[int],
        name: str,
        integer_separators: Optional[Iterable[str]] = None,
    ):
        """
        Definition of a numeral system. A radix must be specified for each integer position
        (left argument) and for each fractional position (right argument).
        Note that the integer position are counted from right to left (starting from the ';'
        symbol and going to the left).

        :param left: Radix list for the integer part
        :param right: Radix list for the fractional part
        :param name: Name of this numeral system
        :param integer_separators: List of string separators, used
        for displaying the integer part of the number
        """
        self.left: LoopingList[int] = LoopingList(left)
        self.right: LoopingList[int] = LoopingList(right)
        self.name = name
        if integer_separators is not None:
            self.integer_separators: LoopingList[str] = LoopingList(
                integer_separators)
        else:
            self.integer_separators: LoopingList[str] = LoopingList([
                "," if x != 10 else "" for x in left
            ])

        # Record the new RadixBase
        RadixBase.name_to_base[self.name] = self

        # Build a class inheriting from BasedReal, that will use this RadixBase as
        # its numeral system.
        type_name = "".join(map(str.capitalize, self.name.split("_")))
        new_type = type(type_name, (BasedReal,), {"base": self})
        setattr(current_module, type_name, new_type)

        # Store the newly created BasedReal class
        self.type: Type[BasedReal] = new_type

    def __getitem__(self, pos: int) -> int:
        """
        Return the radix at the specified position. Position 0 represents the last integer
        position before the fractional part (i.e. the position just before the ';' in sexagesimal
        notation, or just before the '.' in decimal notation). Positive positions represent
        the fractional positions, negative positions represent the integer positions.

        :param pos: Position. <= 0 for integer part (with 0 being the right-most integer position),
                    > 0 for fractional part
        :return: Radix at the specified position
        """
        if pos <= 0:
            return self.left[pos - 1]
        else:
            return self.right[pos - 1]

    @cached
    def float_at_pos(self, pos):
        factor = 1.0
        if pos > 0:
            for i in range(pos):
                factor /= self.right[i]
            return factor
        elif pos == 0:
            return factor
        else:
            for i in range(-pos):
                factor *= self.left[i]
            return factor

    @cached
    def mul_factor(self, i, j):
        numerator = 1
        for k in range(1, i + j + 1):
            numerator *= self[k]
        denom_i = 1
        for k in range(1, i + 1):
            denom_i *= self[k]
        denom_j = 1
        for k in range(1, j + 1):
            denom_j *= self[k]
        if numerator % (denom_i * denom_j) == 0:
            return numerator // (denom_i * denom_j)
        return numerator / (denom_i * denom_j)


def ndigit_for_radix(radix: int) -> int:
    """
    Compute how many ten-radix digits are needed to represent a position of
    the specified radix.

    >>> ndigit_for_radix(10)
    1
    >>> ndigit_for_radix(60)
    2

    :param radix:
    :return:
    """
    return int(np.ceil(np.log10(radix)))


def trim_zeros(left, right):
    for i, n in enumerate(left):
        if n != 0:
            break
        left = left[1:]

    offset = 0

    for i in right[::-1]:
        if i != 0:
            break
        right = right[:-1]
        offset -= 1

    return left, right, offset


class BasedReal(Real):
    """
    Abstract class allowing to represent a value in a specific RadixBase.
    Each time a new RadixBase object is recorded, a new class inheriting from BasedReal
    is created and recorded in the module namespace.
    The RadixBase to be used will be placed in the class attribute 'base'

    Attributes:
        left        The typle of values at integer positions (from right to left)
        right       The tuple of values at fractional positions
        remainder       When a computation requires more precision than the precision
                            of this number, we store a floating remainder to keep track of it
        sign            The sign of this number

    Class attributes:
        base            A RadixBase object (will be attributed dynamically to the children inheriting this class)
    """

    base: RadixBase
    __left: Tuple[int]
    __right: Tuple[int]
    __remainder: float
    __sign: Union[Literal[-1], Literal[1]]
    __slots__ = ('base', '__left', '__right', '__remainder', '__sign')

    def __check_range(self):
        """
        Checks that the given values are in the range of the base and are integers.
        """
        if self.sign not in (-1, 1):
            raise ValueError("Sign should be -1 or 1")
        for x in self[:]:
            if isinstance(x, float):
                raise IllegalFloatValueError(x)
        for i, s in enumerate(self.left[::-1]):
            if s < 0. or s > self.base[-i]:
                raise IllegalBaseValueError(self.base, self.base[-i], s)
        for i, s in enumerate(self.left):
            if s < 0. or s > self.base[i + 1]:
                raise IllegalBaseValueError(self.base, self.base[i + 1], s)

    @cached
    def __new__(cls, *args, remainder=0.0, sign=1):
        """Constructs a number with a given radix.

        Takes :
        - a string,
        - 2 iterables representing integral part and fractional part
        - a BasedReal with a significant number of digits,
        - a Number with a significant number of digits
        - multiple integers representing an integral number in current base

        :param remainder: When a computation requires more precision than the precision
                            of this number, we store a floating remainder to keep track of it, defaults to 0.0
        :type remainder: float, optional
        :param sign: The sign of this number, defaults to 1
        :type sign: int, optional
        :raises ValueError: Unexpected arguments
        :raises IllegalFloatValueError: Values in arguments contain illegal float values
        :raises IllegalBaseValueError: Values in arguments contain out of range values
        :return: new based number
        :rtype: BasedReal
        """
        if cls is BasedReal:
            raise TypeError("Can't instanciate abstract class BasedReal")
        self = super().__new__(cls)
        self.__left: Tuple[int] = ()
        self.__right: Tuple[int] = ()
        self.__remainder = remainder
        self.__sign = sign
        if np.all([isinstance(x, int) for x in args]):
            return cls.__new__(cls, args, (), remainder=remainder, sign=sign)
        elif len(args) == 2:
            if isinstance(args[0], BasedReal):
                return args[0].to_base(cls.base, args[1])
            elif isinstance(args[0], Number):
                return cls.from_float(args[0], args[1])
            elif isinstance(args[0], tuple) and isinstance(args[1], tuple):
                self.__left = args[0]
                self.__right = args[1]
            elif all([isinstance(a, Iterable) and not isinstance(a, str) for a in args]):
                return cls.__new__(cls, tuple(args[0]), tuple(args[1]), remainder=remainder, sign=sign)
            else:
                raise ValueError("Incorrect parameters at BasedReal creation")
        elif len(args) == 1:
            if isinstance(args[0], str):
                return cls.from_string(args[0])
            raise ValueError(
                "Please specify a number of significant positions" if isinstance(args[0], Number)
                else "Incorrect parameters at BasedReal creation"
            )
        elif len(args) == 0:
            raise ValueError(
                "Incorrect number of parameter at BasedReal creation")

        self.__check_range()

        if self.__simplify_integer_part():
            return cls.__new__(cls, self.left, self.right, remainder=self.remainder, sign=self.sign)

        if len(self.__left) == 0:
            self.__left = (0,)

        return self

    @property
    def left(self):
        return self.__left

    @property
    def right(self):
        return self.__right

    @property
    def remainder(self):
        return self.__remainder

    @property
    def sign(self):
        return self.__sign

    @property
    def significant(self):
        return len(self.right)

    def to_fraction(self) -> Fraction:
        """
        :return: this BasedReal as a Fraction object.
        """
        return Fraction(float(self))

    @classmethod
    def from_fraction(
        cls,
        fraction: Fraction,
        remainder=0.0,
        significant: Optional[int] = None,
    ) -> "BasedReal":
        """
        :param fraction: a Fraction object
        :param remainder: remainder to be added
        :param significant: signifcant precision desired
        :return: a BasedReal object computed from a Fraction
        """

        res: BasedReal = cls.from_float(
            float(fraction), significant or 100)

        return cls(res.left,
                   res.right if significant else trim_zeros(
                       res.left, res.right)[1],
                   remainder=remainder,
                   sign=res.sign
                   )

    def __repr__(self) -> str:
        """
        Convert to string representation.
        Note that this representation is rounded (with respect to the
         remainder attribute) not truncated

        :return: String representation of this number
        """
        nv: BasedReal = round(self)
        if nv.base.name == "decimal":
            return "".join(str(v) for v in nv.left) + "." + "".join(str(v) for v in nv.right)
        res = ""
        if nv.sign < 0:
            res += "-"

        for i in range(len(nv.left)):
            if i > 0:
                res += nv.base.integer_separators[i]
            num = str(nv.left[i])
            digit = ndigit_for_radix(nv.base.left[i])
            res += "0" * (digit - len(num)) + num

        res += " ; "

        for i in range(len(nv.right)):
            num = str(nv.right[i])
            digit = ndigit_for_radix(nv.base.right[i])
            res += "0" * (digit - len(num)) + num

            if i < len(nv.right) - 1:
                res += ","

        return res

    def __str__(self):
        return f'{self.__class__.__name__}({str(self.left)}, {str(self.right)}, remainder={self.remainder}, sign={self.sign})'

    @classmethod
    def from_string(cls, string: str) -> "BasedReal":
        """
        Class method to instantiate a BasedReal object from a string

        >>> Sexagesimal('1, 12; 4, 25')
        01,12 ; 04,25
        >>> Historical('2r 7s 29; 45, 2')
        2r 07s 29 ; 45,02
        >>> Sexagesimal('0 ; 4, 45')
        00 ; 04,45

        :param string: String representation of the number
        :return: a new instance of BasedReal
        """
        base = cls.base

        if base.name == "decimal":
            return cls.from_float(float(string), len(string))

        string = string.strip().lower()
        if len(string) == 0:
            raise EmptyStringException("String is empty")
        if string[0] == "-":
            sign = -1
            string = string[1:]
        else:
            sign = 1
        left_right = string.split(";")
        if len(left_right) < 2:
            left = left_right[0]
            right = ""
        elif len(left_right) == 2:
            left, right = left_right
        else:
            raise TooManySeparators("Too many separators in string")

        left = left.strip()
        right = right.strip()

        left_numbers = []
        right_numbers = []

        if len(right) > 0:
            right_numbers = [int(i) for i in right.split(",")]

        if len(left) > 0:
            rleft = left[::-1]
            for i in range(len(left)):
                separator = base.integer_separators[-i - 1].strip().lower()
                if separator != "":
                    split = rleft.split(separator, 1)
                    if len(split) == 1:
                        rem = split[0]
                        break
                    value, rem = split
                else:
                    value = rleft[0]
                    rem = rleft[1:]
                left_numbers.insert(0, int(value[::-1]))
                rleft = rem.strip()
                if len(rleft) == 1:
                    break
            left_numbers.insert(0, int(rleft[::-1]))

        return cls(left_numbers, right_numbers, sign=sign)

    def resize(self, significant: int):
        """
        Resizes and returns a new BasedReal object to the specified precision

        >>> n = Sexagesimal('02, 02; 07, 23, 55, 11, 51, 21, 36')
        >>> n
        02,02 ; 07,23,55,11,51,21,36
        >>> n.remainder
        0.0
        >>> n1 = n.resize(4)
        >>> n1.right
        (7, 23, 55, 11)
        >>> n1.remainder
        0.856
        >>> n1.resize(7)
        02,02 ; 07,23,55,11,51,21,36

        :param significant: Number of desired significant positions
        :return: self
        """
        if significant == len(self.right):
            return self
        factor = self.base.float_at_pos(len(self.right))
        remainderValue = factor * self.remainder
        if significant > len(self.right):
            rem = type(self).from_float(
                self.sign * remainderValue, significant)
            return type(self)(self.left, self.right + rem.right[len(self.right):], remainder=rem.remainder, sign=self.sign)
        elif significant >= 0:
            remainder = type(self)(
                (), self.right[significant:], remainder=self.remainder)

            return type(self)(self.left, self.right[:significant], remainder=float(remainder), sign=self.sign)
        else:
            raise NotImplementedError()

    def __simplify_integer_part(self):
        """
        Remove the useless trailing zeros in the integer part
        :return: self
        """
        count = 0
        for i in self.left:
            if i != 0:
                break
            count += 1
        if count > 0:
            self.__left = self.left[count:]

        return count != 0

    def __trunc__(self):
        return int(float(self))

    def truncate(self, n: int) -> "BasedReal":
        """
        Truncate this BasedReal object to the specified precision

        >>> n = Sexagesimal('02, 02; 07, 23, 55, 11, 51, 21, 36')
        >>> n
        02,02 ; 07,23,55,11,51,21,36
        >>> n = n.truncate(3); n
        02,02 ; 07,23,55
        >>> n = n.resize(7); n
        02,02 ; 07,23,55,00,00,00,00

        :param n: Number of desired significant positions
        :return:
        """
        if n > len(self.right):
            return self
        return type(self)(self.left, self.right[:n], sign=self.sign)

    def shift(self, i: int) -> "BasedReal":
        if i == 0:
            return self

        left_right = (0,) * i + self[:] + (0,) * -i

        offset = len(self.left) if i > 0 else len(self.left) - i

        left = left_right[:offset]
        right = left_right[offset:-i if -i > offset else None]

        return type(self)(left, right, remainder=self.remainder, sign=self.sign)

    def __round__(self, significant: Optional[int] = None):
        """
        Round this BasedReal object to the specified precision.
        If no precision is specified, the rounding is performed with respect to the
        remainder attribute.

        >>> n = Sexagesimal('02, 02; 07, 23, 55, 11, 51, 21, 36')
        >>> n
        02,02 ; 07,23,55,11,51,21,36
        >>> round(n, 4)
        02,02 ; 07,23,55,12

        :param significant: Number of desired significant positions
        :return: self
        """
        if significant is None:
            significant = len(self.right)
        n = self.resize(significant)
        if n.remainder >= 0.5:
            n += type(self)(1, sign=self.sign).shift(significant)
        return n.truncate(significant)

    def __getitem__(self, key):
        """
        Allow to get a specific position value of this BasedReal object
        by specifying an index. The position 0 corresponds to the right-most integer position.
        Negative positions correspond to the other integer positions, positive
        positions correspond to the fractional positions.

        :param key: desired index
        :return: value at the specified position
        """
        if isinstance(key, slice):
            array = self.left + self.right
            start = key.start + \
                len(self.left) - 1 if key.start is not None else None
            stop = key.stop + len(self.left) - \
                1 if key.stop is not None else None
            return array[start:stop:key.step]
        elif isinstance(key, int):
            if -len(self.left) < key <= 0:
                return self.left[key - 1]
            elif len(self.right) >= key > 0:
                return self.right[key - 1]
            else:
                raise IndexError
        else:
            raise TypeError

    @classmethod
    def from_float(cls, floa: float, significant: int) -> "BasedReal":
        """
        Class method to produce a new BasedReal object from a floating number

        >>> Sexagesimal.from_float(1/3, 4)
        00 ; 20,00,00,00

        :param floa: floating value of the number
        :param significant: precision of the number
        :return: a new BasedReal object
        """
        base = cls.base
        sign = int(np.sign(floa)) or 1
        floa *= sign

        pos = 0
        max_integer = 1

        while floa >= max_integer:
            max_integer *= base.left[pos]
            pos += 1

        left = [0] * pos
        right = [0] * significant

        int_factor = max_integer

        for i in range(pos):
            int_factor //= base.left[i]
            position_value = int(floa / int_factor)
            floa -= position_value * int_factor
            left[i] = position_value

        factor = 1.0
        for i in range(significant):
            factor /= base.right[i]
            position_value = int(floa / factor)
            floa -= position_value * factor
            right[i] = position_value

        remainder = floa / factor
        return cls(tuple(left), tuple(right), remainder=remainder, sign=sign)

    @classmethod
    def zero(cls, significant: int) -> "BasedReal":
        """
        Class method to produce a zero number of the specified precision

        >>> Sexagesimal.zero(7)
        00 ; 00,00,00,00,00,00,00

        :param significant: desired precision
        :return: a zero number
        """
        return cls.from_float(0, significant)

    @classmethod
    def one(cls, significant: int) -> "BasedReal":
        """
        Class method to produce a unit number of the specified precision

        >>> Sexagesimal.one(5)
        01 ; 00,00,00,00,00

        :param significant: desired precision
        :return: a unit number
        """
        return cls.from_float(1, significant)

    @classmethod
    def from_int(cls, value: int, significant=0) -> "BasedReal":
        """
        Class method to produce a new BasedReal object from an integer number

        >>> Sexagesimal.from_int(12, 4)
        12 ; 00,00,00,00

        :param value: integer value of the number
        :param significant: precision of the number
        :return: a new BasedReal object
        """
        return cls.from_float(int(value), significant=significant)

    def __float__(self) -> float:
        """
        Compute the float value of this BasedReal object

        >>> float(Sexagesimal('01;20,00'))
        1.3333333333333333
        >>> float(Sexagesimal('14;30,00'))
        14.5

        :return: float representation of this BasedReal object
        """
        value = 0.0
        factor = 1.0
        for i in range(len(self.left)):
            value += factor * self.left[-i - 1]
            factor *= self.base.left[i]
        factor = 1.0
        for i in range(len(self.right)):
            factor /= self.base.right[i]
            value += factor * self.right[i]

        value += factor * self.remainder
        return float(value * self.sign)

    @staticmethod
    def __fractionnal_position_base_to_base(
        value: int, pos: int, base1: RadixBase, base2: RadixBase, significant: int
    ) -> "BasedReal":
        left = [0]
        right = [0] * significant

        denom = gmpy.mpz(1)
        for i in range(pos + 1):
            denom *= gmpy.mpz(base1.right[i])

        num = gmpy.mpz(value)
        rem = 0
        for i in range(significant):
            num *= gmpy.mpz(base2.right[i])
            quo = num // denom
            rem = num % denom
            right[i] = int(quo)
            num = rem

        # remainder = 0.0
        gros_rem = (gmpy.mpz(1000000000) * rem) // denom
        remainder = int(gros_rem) / 1000000000

        return base2.type(left, right, remainder=remainder, sign=1)

    def to_base(self, base: RadixBase, significant: int) -> "BasedReal":
        """
        Convert this number to the specified base

        >>> a = Sexagesimal('0; 20, 00, 00')
        >>> Decimal(a, 7)
        0.3333333

        :param base: a RadixBase object
        :param significant: the precision of the result
        :return: a new BasedReal object
        """
        return base.type.from_float(float(self), significant)

    def __int_imul(self, n: int) -> "BasedReal":
        for i in range(-len(self.left) + 1, len(self.right) + 1):
            self[i] *= n
        self.remainder *= n
        return self

    def __float_imul(self, f: float) -> "BasedReal":
        for i in range(-len(self.left) + 1, len(self.right) + 1):
            self[i] *= f
        self.remainder *= f
        for i in range(-len(self.left) + 1, len(self.right) + 1):
            frac, whole = math.modf(self[i])
            self[i] = int(whole)
            if i != len(self.right):
                self[i + 1] += frac * self.base[i + 1]
            else:
                self.remainder += frac
        return self

    def __int_idiv(self, n: int, significant: Optional[int] = None) -> "BasedReal":
        if significant:
            self.resize(significant)
        self.remainder /= n
        for i in range(-len(self.left) + 1, len(self.right) + 1):
            q = self[i] // n
            r = self[i] % n
            self[i] = q
            if i != len(self.right):
                self[i + 1] += r * self.base[i + 1]
            else:
                self.remainder += r * self.base[i + 1] / (self.base[i] * n)
        return self

    def __div__(self, other) -> Union[float, "BasedReal"]:
        if isinstance(other, type(self)):
            return self.division(other, 255)
        else:
            return float(self) / float(other)

    def division(self, other: "BasedReal", significant: int) -> "BasedReal":
        """
        Divide this BasedReal object with another

        :param other: the other BasedReal object
        :param significant: the number of desired significant positions
        :return: the division of the two BasedReal objects
        """
        if not isinstance(self, type(other)) or not isinstance(other, type(self)):
            raise TypeMismatch(
                "Conversion needed for operation between %s and %s"
                % (str(type(self)), str(type(other)))
            )

        final_sign = self.sign * other.sign

        num_nv = copy.deepcopy(self)
        denom_nv = copy.deepcopy(other)
        num_nv.sign = 1
        denom_nv.sign = 1

        q_res = self.zero(significant)

        multiplier = 1

        for i in range(significant + 1):
            q, r = num_nv.euclidian_div(denom_nv)
            q.__int_idiv(multiplier, significant=significant)
            q_res += q

            r.__int_imul(self.base.right[i])
            multiplier *= self.base.right[i]

            num_nv = r

        q_res.remainder += (float(num_nv) / float(denom_nv)
                            ) / self.base.right[i]
        q_res.sign = final_sign

        return q_res

    def __add__(self, other: "BasedReal") -> "BasedReal":
        """
        Implementation of the add + operator

        >>> Sexagesimal('01, 21; 47, 25') + Sexagesimal('45; 32, 14, 22')
        02,07 ; 19,39,22

        :param other:
        :return: the sum of the two BasedReal objects
        """
        if not isinstance(self, type(other)) or not isinstance(other, type(self)):
            return self + self.from_float(float(other), significant=len(self.right))

        maxright = max(len(self.right), len(other.right))
        maxleft = max(len(self.left), len(other.left))
        va = self.resize(maxright)
        vb = other.resize(maxright)

        sign = va.sign if abs(va) > abs(vb) else vb.sign
        if sign < 0:
            va = -va
            vb = -vb

        remainder = va.remainder * va.sign + vb.remainder * vb.sign

        numbers = [int(remainder)] + [0] * max(len(va[:]), len(vb[:]))
        remainder = remainder - int(remainder)

        def add(array: List[int], values: "BasedReal"):
            to_add = tuple(
                values.sign * x for x in values[::-1]) + (0,) * (len(numbers) - len(values[:]) - 1)
            for i, r in enumerate(to_add):
                array[i] += r
                factor = self.base[maxright - i]
                n = array[i]
                if n < 0 or n >= factor:
                    array[i] = n % factor
                    array[i + 1] += 1 if n > 0 else -1

        add(numbers, va)
        add(numbers, vb)

        numbers = tuple(abs(x) for x in numbers[::-1])
        left = numbers[:maxleft + 1]
        right = numbers[maxleft + 1:]

        return type(self)(left, right, remainder=remainder, sign=sign)

    def __radd__(self, other):
        """other + self"""
        return self + other

    def __sub__(self, other: "BasedReal") -> "BasedReal":
        """
        :param other: other BasedReal Object
        :return: self
        """
        return self + -other

    def __rsub__(self, other):
        """other - self"""
        return other + -self

    def __rtruediv__(self, other):
        """other / self"""
        raise NotImplementedError

    def __pow__(self, exponent):
        """self**exponent; should promote to float or complex when necessary."""
        if exponent == 0:
            return self.one(0)
        elif exponent > 0:
            res = self
            for _ in range(1, exponent):
                res *= self
        else:
            res = 1
            for _ in range(0, -exponent):
                res /= self

    def __rpow__(self, base):
        """base ** self"""
        raise NotImplementedError

    def conjugate(self):
        """(x+y*i).conjugate() returns (x-y*i)."""
        raise NotImplementedError

    def __rfloordiv__(self, other):
        """other // self: The floor() of other/self."""
        raise NotImplementedError

    def __rmod__(self, other):
        """other % self"""
        raise NotImplementedError

    def __neg__(self) -> "BasedReal":
        """
        Implementation of the neg operator

        >>> -Sexagesimal('-12; 14, 15')
        12 ; 14,15

        :return: the opposite of self
        """
        return type(self)(self.left, self.right, remainder=self.remainder, sign=-self.sign)

    def __pos__(self) -> "BasedReal":
        """
        :return: self
        """
        return self

    def __abs__(self) -> "BasedReal":
        """
        Implementation of the abs operator.

        >>> abs(Sexagesimal('-12; 14, 15'))
        12 ; 14,15

        :return: the absolute value of self
        """
        if self.sign >= 0:
            return self
        return -self

    def __mul__(self, other: "BasedReal") -> "BasedReal":
        """
        Implementation of the multiplication operator

        >>> Sexagesimal('01, 12; 04, 17') * Sexagesimal('7; 45, 55')
        09,19 ; 39,15,40,35

        :param other: The other BasedReal to multiply
        :return: The product of the 2 BasedReal object
        """
        if not isinstance(self, type(other)) or not isinstance(other, type(self)):
            return self * self.from_float(other, self.significant)

        sign = self.sign * other.sign

        max_right = max(self.significant, other.significant)

        va = self.resize(max_right)
        vb = other.resize(max_right)

        numbers = [[0] * i + [fv * s for s in vb[:]][::-1]
                   for i, fv in enumerate(va[::-1])]

        count = [0] * max(len(x) for x in numbers) + [0]

        for n in numbers:
            for i, r in enumerate(n):
                count[i] += r
                factor = self.base[max_right - i]
                n = count[i]
                if n < 0 or n >= factor:
                    count[i] = n % factor
                    count[i + 1] += n // factor

        while count[-1] != 0:
            factor = self.base[max_right - len(count)]
            n = count[-1]
            count[-1] = n % factor
            count.append(n // factor)

        res = type(self)(*tuple(count[::-1]))
        res = res.shift(2 * max_right)

        vb_rem = self.base.float_at_pos(max_right) * vb.remainder
        va_rem = self.base.float_at_pos(max_right) * va.remainder
        res += float(va) * vb_rem + float(vb) * va_rem + va_rem * vb_rem

        if sign < 0:
            res = -res

        return res

    def __rmul__(self, other):
        """other * self"""
        raise self * other

    def euclidian_div(self, other):
        raise NotImplementedError()

    def __floordiv__(self, other: "BasedReal") -> "BasedReal":
        """
        self // other

        :param other: the other BasedReal object
        :return: the quotient in the euclidian division of self with other
        """
        return self.euclidian_div(other)[0]

    def __mod__(self, other: "BasedReal") -> "BasedReal":
        """
        self % other

        :param other: the other BasedReal object
        :return: the remainder in the euclidian division of self with other
        """
        return self.euclidian_div(other)[1]

    def __truediv__(self, other: "BasedReal") -> "BasedReal":
        """
        Return the division of self with other. NB: To select the precision of
        the result (i.e. its number of significant positions) you should use the
        division method.

        :param other: the other BasedReal object
        :return: the division of self with other
        """
        return self.division(other, max(len(self.right), len(other.right)) + 5)

    def __gt__(self, other: Number) -> bool:
        """
        self > other

        :param other: other  object
        :return: True if self is greater than other, False if not
        """
        return float(self) > float(other)

    def __eq__(self, other: Number) -> bool:
        """
        self == other

        :param other: other BasedReal object
        :return: True if both BasedReal objects are equal, False if not
        """

        if not isinstance(self, type(other)) or len(self.right) != len(other.right):
            return float(self) == float(other)

        return self.sign == other.sign and self.right == other.right and self.left == other.left and self.remainder == other.remainder

    def __ne__(self, other: object) -> bool:
        """
        self != other

        :param other: other BasedReal object
        :return: True if self and other are different, False if not
        """
        return not self == other

    def __ge__(self, other: "BasedReal") -> bool:
        """
        self >= other

        :param other: other BasedReal object
        :return: True if self is greater or equal to other, False if not
        """
        return self == other or self > other

    def __lt__(self, other: "BasedReal") -> bool:
        """
        self < other

        >>> Sexagesimal('01, 27; 00, 03') < Sexagesimal('01, 25; 00, 12')
        False
        >>> Sexagesimal('-01, 27; 00, 03') < Sexagesimal('01, 25; 00, 12')
        True

        :param other: other BasedReal object
        :return: True if self is greater than other, False if not
        """
        return not self >= other

    def __le__(self, other: "BasedReal") -> bool:
        """
        self <= other

        >>> Sexagesimal('01, 25;') <= Sexagesimal('01, 25; 00, 00')
        True
        >>> Sexagesimal('01, 27; 00, 03') <= Sexagesimal('01, 25; 00, 12')
        False
        >>> Sexagesimal('-01, 27; 00, 03') <= Sexagesimal('01, 25; 00, 12')
        True

        :param other: other BasedReal object
        :return: True if self is greater or equal to other, False if not
        """
        return not self > other

    def __floor__(self):
        """Finds the greatest Integral <= self."""
        return self.__trunc__() + 1 if self.sign < 0 else 0

    def __ceil__(self):
        """Finds the least Integral >= self."""
        return self.__trunc__() + 1 if self.sign > 0 else 0


# here we define standard bases and automatically generate the corresponding BasedReal classes
RadixBase([10], [10], "decimal")
RadixBase([60], [60], "sexagesimal")
RadixBase([60], [60], "floating_sexagesimal")
RadixBase([10, 12, 30], [60], "historical", ["", "r ", "s "])
RadixBase([10], [100], "historical_decimal")
RadixBase([10], [60], "integer_and_sexagesimal")
RadixBase([10], [60], "integer and sexagesimal")
RadixBase([10], [24, 60], "temporal")
# add new definitions here, corresponding BasedReal inherited classes will be automatically generated