import binascii
from geoalchemy2.compat import PY3, str as str_

try:
    from sqlalchemy.sql import functions
    from sqlalchemy.sql.functions import FunctionElement
except ImportError:  # SQLA < 0.9  # pragma: no cover
    from sqlalchemy.sql import expression as functions
    from sqlalchemy.sql.expression import FunctionElement
from sqlalchemy.types import to_instance
from sqlalchemy.ext.compiler import compiles


class _SpatialElement(functions.Function):
    """
    The base class for :class:`geoalchemy2.elements.WKTElement` and
    :class:`geoalchemy2.elements.WKBElement`.

    The first argument passed to the constructor is the data wrapped
    by the ``_SpatialElement` object being constructed.

    Additional arguments:

    ``srid``

        An integer representing the spatial reference system. E.g. 4326.
        Default value is -1, which means no/unknown reference system.

    ``extended``

        A boolean indicating whether the extended format (EWKT or EWKB)
        is used. Default is ``False``.

    ``use_st_prefix``

        A boolean indicating whether the ST_ versions of the GeomFromEWKT
        and GeomFromEWKB functions are used. Default is ``True``.

    """

    def __init__(self, data, srid=-1, extended=False, use_st_prefix=True):
        self.srid = srid
        self.data = data
        self.extended = extended
        self.use_st_prefix = use_st_prefix
        if self.extended:
            args = [self.geom_from_extended_version, self.data]
        else:
            args = [self.geom_from, self.data, self.srid]
        if not self.use_st_prefix:
            args[0] = args[0].lstrip('ST')
        functions.Function.__init__(self, *args)

    def __str__(self):
        return self.desc

    def __repr__(self):
        return "<%s at 0x%x; %s>" % \
            (self.__class__.__name__, id(self), self)  # pragma: no cover

    def __getattr__(self, name):
        #
        # This is how things like lake.geom.ST_Buffer(2) creates
        # SQL expressions of this form:
        #
        # ST_Buffer(ST_GeomFromWKB(:ST_GeomFromWKB_1), :param_1)
        #

        # We create our own _FunctionGenerator here, and use it in place of
        # SQLAlchemy's "func" object. This is to be able to "bind" the
        # function to the SQL expression. See also GenericFunction above.

        func_ = functions._FunctionGenerator(expr=self)
        return getattr(func_, name)

    def __getstate__(self):
        state = {
            'srid': self.srid,
            'data': str(self),
            'extended': self.extended,
            'use_st_prefix': self.use_st_prefix,
            'name': self.name,
        }
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.data = self._data_from_desc(state['data'])
        args = [self.name, self.data]
        if not self.extended:
            args.append(self.srid)
        # we need to call Function.__init__ to properly initialize SQLAlchemy's
        # internal states
        functions.Function.__init__(self, *args)

    @staticmethod
    def _data_from_desc(desc):
        raise NotImplementedError()


class WKTElement(_SpatialElement):
    """
    Instances of this class wrap a WKT or EWKT value.

    Usage examples::

        wkt_element_1 = WKTElement('POINT(5 45)')
        wkt_element_2 = WKTElement('POINT(5 45)', srid=4326)
        wkt_element_3 = WKTElement('SRID=4326;POINT(5 45)', extended=True)
    """

    geom_from = 'ST_GeomFromText'
    geom_from_extended_version = 'ST_GeomFromEWKT'

    @property
    def desc(self):
        """
        This element's description string.
        """
        return self.data

    @staticmethod
    def _data_from_desc(desc):
        return desc


class WKBElement(_SpatialElement):
    """
    Instances of this class wrap a WKB or EWKB value.

    Geometry values read from the database are converted to instances of this
    type. In most cases you won't need to create ``WKBElement`` instances
    yourself.

    Note: you can create ``WKBElement`` objects from Shapely geometries
    using the :func:`geoalchemy2.shape.from_shape` function.
    """

    geom_from = 'ST_GeomFromWKB'
    geom_from_extended_version = 'ST_GeomFromEWKB'

    @property
    def desc(self):
        """
        This element's description string.
        """
        if isinstance(self.data, str_):
            return self.data
        desc = binascii.hexlify(self.data)
        if PY3:
            # hexlify returns a bytes object on py3
            desc = str(desc, encoding="utf-8")
        return desc

    @staticmethod
    def _data_from_desc(desc):
        if PY3:
            desc = desc.encode(encoding="utf-8")
        return binascii.unhexlify(desc)


class RasterElement(FunctionElement):
    """
    Instances of this class wrap a ``raster`` value. Raster values read
    from the database are converted to instances of this type. In
    most cases you won't need to create ``RasterElement`` instances
    yourself.
    """

    name = 'raster'

    def __init__(self, data):
        self.data = data
        FunctionElement.__init__(self, self.data)

    def __str__(self):
        return self.desc  # pragma: no cover

    def __repr__(self):
        return "<%s at 0x%x; %r>" % \
            (self.__class__.__name__, id(self), self.desc)  # pragma: no cover

    @property
    def desc(self):
        """
        This element's description string.
        """
        desc = binascii.hexlify(self.data)
        if PY3:
            # hexlify returns a bytes object on py3
            desc = str(desc, encoding="utf-8")

        if len(desc) < 30:
            return desc

        return desc[:30] + '...'  # pragma: no cover

    def __getattr__(self, name):
        #
        # This is how things like ocean.rast.ST_Value(...) creates
        # SQL expressions of this form:
        #
        # ST_Value(:ST_GeomFromWKB_1), :param_1)
        #

        # We create our own _FunctionGenerator here, and use it in place of
        # SQLAlchemy's "func" object. This is to be able to "bind" the
        # function to the SQL expression. See also GenericFunction.

        func_ = functions._FunctionGenerator(expr=self)
        return getattr(func_, name)


@compiles(RasterElement)
def compile_RasterElement(element, compiler, **kw):
    """
    This function makes sure the :class:`geoalchemy2.elements.RasterElement`
    contents are correctly casted to the ``raster`` type before using it.

    The other elements in this module don't need such a function because
    they are derived from :class:`functions.Function`. For the
    :class:`geoalchemy2.elements.RasterElement` class however it would not be
    of any use to have it compile to ``raster('...')`` so it is compiled to
    ``'...'::raster`` by this function.
    """
    return "%s::raster" % compiler.process(element.clauses)


class CompositeElement(FunctionElement):
    """
    Instances of this class wrap a Postgres composite type.
    """

    def __init__(self, base, field, type_):
        self.name = field
        self.type = to_instance(type_)

        super(CompositeElement, self).__init__(base)


@compiles(CompositeElement)
def _compile_pgelem(expr, compiler, **kw):
    return '(%s).%s' % (compiler.process(expr.clauses, **kw), expr.name)
