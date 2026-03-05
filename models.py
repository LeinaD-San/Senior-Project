from sqlalchemy import Column, ForeignKey, Integer, String, Text, Float
from database import Base

class Trip(Base):
    __tablename__ = 'trips'

    id = Column(Integer, primary_key=True, index=True)
    title= Column(String, nullable=False)
    destination = Column(String, nullable=False)

class TripItem(Base):
    __tablename__ = 'trip_item'

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey('trips.id'), nullable =False)

    day = Column(Integer, default = 1)

#this is the new position, this is implemented since there is no guaranteed order. 
#therefore position will be the order police for items within the same trip and same day. 
    position = Column(Integer, nullable=False, default =0) #added by Nick^^

    place_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    notes = Column(Text, default='')

    lat = Column(Float, nullable=True)
    lng = Column(Float,nullable=True)
    address = Column(String, nullable=True)
    rating = Column(Float, nullable=True)
    