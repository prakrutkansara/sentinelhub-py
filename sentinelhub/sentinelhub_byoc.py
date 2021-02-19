"""
Module implementing an interface with Sentinel Hub Bring your own COG service
"""
from dataclasses import field, dataclass
from datetime import datetime
from typing import Optional, Union

from dataclasses_json import config as dataclass_config
from dataclasses_json import dataclass_json, LetterCase, Undefined, CatchAll

from .data_collections import DataCollection
from .config import SHConfig
from .constants import RequestType, MimeType
from .download.sentinelhub_client import SentinelHubDownloadClient
from .geometry import Geometry
from .sh_utils import iter_pages, remove_undefined, from_sh_datetime, to_sh_datetime


datetime_config = dataclass_config(encoder=to_sh_datetime, decoder=from_sh_datetime,
                                   letter_case=LetterCase.CAMEL)

geometry_config = dataclass_config(encoder=Geometry.get_geojson,
                                   decoder=lambda x: Geometry.from_geojson(x) if x else None,
                                   exclude=lambda x: x is None, letter_case=LetterCase.CAMEL)


@dataclass_json(letter_case=LetterCase.CAMEL, undefined=Undefined.INCLUDE)
@dataclass
class ByocCollectionAdditionalData:
    """ Dataclass to hold BYOC collection additional data
    """
    other_data: CatchAll
    bands: Optional[dict] = None
    max_meters_per_pixel: Optional[float] = None
    max_meters_per_pixel_override: Optional[float] = None


@dataclass_json(letter_case=LetterCase.CAMEL, undefined=Undefined.INCLUDE)
@dataclass
class ByocCollection:
    """ Dataclass to hold BYOC collection data
    """
    name: str
    s3_bucket: str
    other_data: CatchAll
    collection_id: Optional[str] = field(metadata=dataclass_config(field_name='id'), default=None)
    user_id: Optional[str] = None
    created: Optional[datetime] = field(metadata=datetime_config, default=None)
    additional_data: Optional[ByocCollectionAdditionalData] = None
    no_data: Optional[Union[int, float]] = None

    def to_data_collection(self):
        """ Returns a DataCollection enum for this BYOC collection
        """
        if self.additional_data and self.additional_data.bands:
            band_names = tuple(self.additional_data.bands)
            return DataCollection.define_byoc(collection_id=self.collection_id, bands=band_names)

        return DataCollection.define_byoc(collection_id=self.collection_id)


@dataclass_json(letter_case=LetterCase.CAMEL, undefined=Undefined.INCLUDE)
@dataclass
class ByocTile:
    """ Dataclass to hold BYOC tile data
    """
    path: str
    other_data: CatchAll
    status: Optional[str] = None
    tile_id: Optional[str] = field(metadata=dataclass_config(field_name='id'), default=None)
    tile_geometry: Optional[Geometry] = field(metadata=geometry_config, default=None)
    cover_geometry: Optional[Geometry] = field(metadata=geometry_config, default=None)
    created: Optional[datetime] = field(metadata=datetime_config, default=None)
    sensing_time: Optional[datetime] = field(metadata=datetime_config, default=None)
    additional_data: Optional[dict] = None

    @property
    def tile_geometry_crs(self):
        """ CRS of tile geometry
        """
        return self.tile_geometry.crs if self.tile_geometry and not self.tile_geometry.geometry.is_empty else None

    @property
    def cover_geometry_crs(self):
        """ CRS of tile cover geometry
        """
        return self.cover_geometry.crs if self.cover_geometry and not self.cover_geometry.geometry.is_empty else None

    @property
    def geometry(self):
        """ Tile cover geometry as shapely object
        """
        if self.cover_geometry and not self.cover_geometry.geometry.is_empty:
            return self.cover_geometry.geometry
        return None


class SentinelHubBYOC:
    """ An interface class for Sentinel Hub Bring your own COG (BYOC) API
    For more info check `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#tag/byoc_collection>`.
    """
    def __init__(self, base_url=None, config=None):
        self.config = config or SHConfig()

        base_url = base_url or self.config.sh_base_url
        self.byoc_url = f'{base_url.rstrip("/")}/api/v1/byoc'

        self.client = SentinelHubDownloadClient(config=self.config)

    def iter_collections(self):
        """ Retrieve collections
        `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#operation/getByocCollections>`

        :return: iterator over collections
        """
        url = f'{self.byoc_url}/collections'
        return iter_pages(client=self.client, service_url=url,
                          exception_message='Failed to obtain information about available collections.')

    def get_collection(self, collection):
        """ Get collection by its id
        `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#operation/getByocCollectionById>`

        :param collection: a ByocCollection, dict or collection id string
        :return: dictionary of the collection
        :rtype: dict
        """
        url = f'{self.byoc_url}/collections/{self._parse_id(collection)}'
        return self.client.get_json(url=url, use_session=True)['data']

    def create_collection(self, collection):
        """ Create a new collection
        `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#operation/createByocCollection>`

        :param collection: ByocCollection object or a dictionary
        :return: dictionary of the created collection
        :rtype: dict
        """
        coll = self._to_dict(collection)
        url = f'{self.byoc_url}/collections'
        return self.client.get_json(url=url, post_values=coll, use_session=True)['data']

    def update_collection(self, collection):
        """ Update an existing collection
        `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#operation/updateByocCollectionById>`

        :param collection: ByocCollection object or a dictionary
        """
        coll = self._to_dict(collection)
        url = f'{self.byoc_url}/collections/{self._parse_id(coll)}'
        headers = {'Content-Type': MimeType.JSON.get_string()}
        return self.client.get_json(url=url, request_type=RequestType.PUT, post_values=coll,
                                    headers=headers, use_session=True)

    def delete_collection(self, collection):
        """ Delete existing collection by its id
        `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#operation/deleteByocCollectionById>`

        :param collection: a ByocCollection, dict or collection id string
        """
        url = f'{self.byoc_url}/collections/{self._parse_id(collection)}'
        return self.client.get_json(url=url, request_type=RequestType.DELETE, use_session=True)

    def copy_tiles(self, from_collection, to_collection):
        """ Copy tiles from one collection to another
        `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#operation/copyByocCollectionTiles>`

        :param from_collection: a ByocCollection, dict or collection id string
        :param to_collection: a ByocCollection, dict or collection id string
        """
        url = f'{self.byoc_url}/collections/{self._parse_id(from_collection)}' \
              f'/copyTiles?toCollection={self._parse_id(to_collection)}'
        return self.client.get_json(url=url, request_type=RequestType.POST, use_session=True)

    def iter_tiles(self, collection):
        """ Iterator over collection tiles
        `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#operation/getByocCollectionTiles>`

        :param collection: a ByocCollection, dict or collection id string
        :return: iterator
        """
        url = f'{self.byoc_url}/collections/{self._parse_id(collection)}/tiles'
        return iter_pages(client=self.client, service_url=url,
                          exception_message=f'Failed to obtain information about tiles in ByocCollection '
                                            f'{self._parse_id(collection)}.')

    def get_tile(self, collection, tile):
        """ Get a tile of collection
        `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#operation/getByocCollectionTileById>`

        :param collection: a ByocCollection, dict or collection id string
        :param tile: a ByocTile, dict or tile id string
        :return: dictionary of the tile
        :rtype: dict
        """
        url = f'{self.byoc_url}/collections/{self._parse_id(collection)}/tiles/{self._parse_id(tile)}'
        return self.client.get_json(url=url, use_session=True)['data']

    def create_tile(self, collection, tile):
        """ Create tile within collection
        `BYOC API reference <https://docs.sentinel-hub.com/api/latest/reference/#operation/createByocCollectionTile>`

        :param collection: a ByocCollection, dict or collection id string
        :param tile: a ByocTile or dict
        :return: dictionary of the tile
        :rtype: dict
        """
        _tile = self._to_dict(tile)
        url = f'{self.byoc_url}/collections/{self._parse_id(collection)}/tiles'
        return self.client.get_json(url=url, post_values=_tile, use_session=True)['data']

    def update_tile(self, collection, tile):
        """ Update a tile within collection
        `BYOC API reference
        <https://docs.sentinel-hub.com/api/latest/reference/#operation/updateByocCollectionTileById>`

        :param collection: a ByocCollection, dict or collection id string
        :param tile: a ByocTile or dict
        """
        url = f'{self.byoc_url}/collections/{self._parse_id(collection)}/tiles/{self._parse_id(tile)}'
        headers = {'Content-Type': MimeType.JSON.get_string()}

        _tile = self._to_dict(tile)
        updates = remove_undefined({
            'path': _tile['path'],
            'coverGeometry': _tile.get('coverGeometry'),
            'sensingTime':  _tile.get('sensingTime')
        })

        return self.client.get_json(url=url, request_type=RequestType.PUT, post_values=updates,
                                    headers=headers, use_session=True)['data']

    def delete_tile(self, collection, tile):
        """ Delete a tile from collection
        `BYOC API reference
        <https://docs.sentinel-hub.com/api/latest/reference/#operation/deleteByocCollectionTileById>`

        :param collection: a ByocCollection, dict or collection id string
        :param tile: a ByocTile, dict or tile id string
        """
        url = f'{self.byoc_url}/collections/{self._parse_id(collection)}/tiles/{self._parse_id(tile)}'
        return self.client.get_json(url=url, request_type=RequestType.DELETE, use_session=True)

    @staticmethod
    def _parse_id(data):
        if isinstance(data, (ByocCollection, DataCollection)):
            return data.collection_id
        if isinstance(data, ByocTile):
            return data.tile_id
        if isinstance(data, dict):
            return data['id']
        if isinstance(data, str):
            return data
        raise ValueError(f'Expected a BYOC/Data dataclass, dictionary or a string, got {data}.')

    @staticmethod
    def _to_dict(data):
        """ Constructs dict from an object (either dataclass or dict)
        """
        if isinstance(data, (ByocCollection, ByocTile, ByocCollectionAdditionalData)):
            return data.to_dict()
        if isinstance(data, dict):
            return data
        raise ValueError(f'Expected either a data class (e.g., ByocCollection, ByocTile) or a dict, got {data}.')
