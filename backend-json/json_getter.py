#!/usr/bin/python
# -*- coding: utf-8 -*-
#    This file is part of kothic, the realtime map renderer.

#   kothic is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.

#   kothic is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.

#   You should have received a copy of the GNU General Public License
#   along with kothic.  If not, see <http://www.gnu.org/licenses/>.
#
#   (c) 2012 Kai Krueger
#   (c) 2011 - 2012 Other authors

from twms import projections
from libkomapnik import pixel_size_at_zoom
import json
import psycopg2
from mapcss import MapCSS
import cgi
import os
import sys
import syslog
reload(sys)
sys.setdefaultencoding("utf-8")          # a hack to support UTF-8

debug = 1

try:
  import psyco
  psyco.full()
except ImportError:
  pass
  #print >>sys.stderr, "Psyco import failed. Program may run slower. If you run it on i386 machine, please install Psyco to get best performance."

def log(prio, msg):
    global debug
    syslog.syslog(prio, msg)
    if debug == 1:
        print msg

def get_vectors(database, bbox, zoom, style, vec = "polygon"):
  bbox_p = projections.from4326(bbox, "EPSG:3857")
  geomcolumn = "way"

  pxtolerance = 1.8
  intscalefactor = 10000
  ignore_columns = set(["way_area", "osm_id", geomcolumn, "tags", "z_order"])
  table = {"polygon":"planet_osm_polygon", "line":"planet_osm_line","point":"planet_osm_point", "coastline": "coastlines"}

  
  b = database.cursor()
  if vec != "coastline":
    b.execute("SELECT * FROM %s LIMIT 1;" % table[vec])
    names = [q[0] for q in b.description]
    for i in ignore_columns:
      if i in names:
        names.remove(i)
    names = ",".join(['"'+i+'"' for i in names])


    taghint = "*"
    types = {"line":"line","polygon":"area", "point":"node"}
    adp = ""
    if "get_sql_hints" in dir(style):
      sql_hint = style.get_sql_hints(types[vec], zoom)
      adp = []
      for tp in sql_hint:
        add = []
        for j in tp[0]:
          if j not in names:
            break
        else:
          add.append(tp[1])
        if add:
          add = " OR ".join(add)
          add = "("+add+")"
          adp.append(add)
      adp = " OR ".join(adp)
      if adp:
        adp = adp.replace("&lt;", "<")
        adp = adp.replace("&gt;", ">")


  if vec == "polygon":
    query = """select ST_AsGeoJSON(ST_TransScale(ST_ForceRHR(ST_Intersection(way,SetSRID('BOX3D(%s %s,%s %s)'::box3d,900913))),%s,%s,%s,%s),0) as %s,
                      ST_AsGeoJSON(ST_TransScale(ST_ForceRHR(ST_PointOnSurface(way)),%s,%s,%s,%s),0) as reprpoint, %s from
              (select (ST_Dump(ST_Multi(ST_SimplifyPreserveTopology(ST_Buffer(way,-%s),%s)))).geom as %s, %s from
                (select ST_Union(way) as %s, %s from
                  (select ST_Buffer(way, %s) as %s, %s from
                     %s
                     where (%s)
                       and way && SetSRID('BOX3D(%s %s,%s %s)'::box3d,900913)
                       and way_area > %s
                  ) p
                 group by %s
                ) p
                where ST_Area(way) > %s
                order by ST_Area(way)
              ) p
      """%(bbox_p[0],bbox_p[1],bbox_p[2],bbox_p[3],
          -bbox_p[0],-bbox_p[1],intscalefactor/(bbox_p[2]-bbox_p[0]),intscalefactor/(bbox_p[3]-bbox_p[1]),
          geomcolumn,
          -bbox_p[0],-bbox_p[1],intscalefactor/(bbox_p[2]-bbox_p[0]),intscalefactor/(bbox_p[3]-bbox_p[1]),
          names,
          pixel_size_at_zoom(zoom, pxtolerance),pixel_size_at_zoom(zoom, pxtolerance),
          geomcolumn, names,
          geomcolumn, names,
          pixel_size_at_zoom(zoom, pxtolerance),
          geomcolumn, names,
          table[vec],
          adp,
          bbox_p[0],bbox_p[1],bbox_p[2],bbox_p[3],
          (pixel_size_at_zoom(zoom, pxtolerance)**2)/pxtolerance,
          names,
          pixel_size_at_zoom(zoom, pxtolerance)**2
          )
  elif vec == "line":
    query = """select ST_AsGeoJSON(ST_TransScale(ST_Intersection(way,SetSRID('BOX3D(%s %s,%s %s)'::box3d,900913)),%s,%s,%s,%s),0) as %s, %s from
              (select (ST_Dump(ST_Multi(ST_SimplifyPreserveTopology(ST_LineMerge(way),%s)))).geom as %s, %s from
                (select ST_Union(way) as %s, %s from
                     %s
                     where (%s)
                       and way && SetSRID('BOX3D(%s %s,%s %s)'::box3d,900913)

                 group by %s
                ) p

              ) p
      """%(bbox_p[0],bbox_p[1],bbox_p[2],bbox_p[3],
          -bbox_p[0],-bbox_p[1],intscalefactor/(bbox_p[2]-bbox_p[0]),intscalefactor/(bbox_p[3]-bbox_p[1]),
          geomcolumn, names,
          pixel_size_at_zoom(zoom, pxtolerance),
          geomcolumn, names,
          geomcolumn, names,
          table[vec],
          adp,
          bbox_p[0],bbox_p[1],bbox_p[2],bbox_p[3],

          names,

          )
  elif vec == "point":
    query = """select ST_AsGeoJSON(ST_TransScale(way,%s,%s,%s,%s),0) as %s, %s
                from %s where
                (%s)
                and way && SetSRID('BOX3D(%s %s,%s %s)'::box3d,900913)
               limit 10000
         """%(
             -bbox_p[0],-bbox_p[1],intscalefactor/(bbox_p[2]-bbox_p[0]),intscalefactor/(bbox_p[3]-bbox_p[1]),
             geomcolumn, names,
             table[vec],
             adp,
             bbox_p[0],bbox_p[1],bbox_p[2],bbox_p[3]
             )
  elif vec == "coastline":
    query = """select ST_AsGeoJSON(ST_TransScale(ST_ForceRHR(ST_Intersection(way,SetSRID('BOX3D(%s %s,%s %s)'::box3d,900913))),%s,%s,%s,%s),0) as %s, 'coastline' as "natural" from
              (select (ST_Dump(ST_Multi(ST_SimplifyPreserveTopology(ST_Buffer(way,-%s),%s)))).geom as %s from
                (select ST_Union(way) as %s from
                  (select ST_Buffer(SetSRID(the_geom,900913), %s) as %s from
                     %s
                     where
                        SetSRID(the_geom,900913) && SetSRID('BOX3D(%s %s,%s %s)'::box3d,900913)
                  ) p
                ) p
                where ST_Area(way) > %s
              ) p
      """%(bbox_p[0],bbox_p[1],bbox_p[2],bbox_p[3],
          -bbox_p[0],-bbox_p[1],intscalefactor/(bbox_p[2]-bbox_p[0]),intscalefactor/(bbox_p[3]-bbox_p[1]),
          geomcolumn,
          pixel_size_at_zoom(zoom, pxtolerance),pixel_size_at_zoom(zoom, pxtolerance),
          geomcolumn,
          geomcolumn,
          pixel_size_at_zoom(zoom, pxtolerance),
          geomcolumn,
          table[vec],
          bbox_p[0],bbox_p[1],bbox_p[2],bbox_p[3],
          pixel_size_at_zoom(zoom, pxtolerance)**2
          )
  #print query
  #log(syslog.LOG_INFO,query)
  b = database.cursor()
  b.execute(query)
  names = [q[0] for q in b.description]

  ROWS_FETCHED = 0
  polygons = []

  for row in b.fetchall():
    ROWS_FETCHED += 1
    geom = dict(map(None,names,row))
    for t in geom.keys():
      if not geom[t]:
        del geom[t]
    geojson = json.loads(geom[geomcolumn])
    del geom[geomcolumn]
    if geojson["type"] == "GeometryCollection":
      continue
    if "reprpoint" in geom:
      geojson["reprpoint"] = json.loads(geom["reprpoint"])["coordinates"]
      del geom["reprpoint"]
    prop = {}
    for k,v in geom.iteritems():
      prop[k] = v
      try:
        if int(v) == float(v):
          prop[k] = int(v)
        else:
          prop[k] = float(v)
        if str(prop[k]) != v:  # leading zeros etc.. should be saved
          prop[k] = v
      except:
        pass
    geojson["properties"] = prop
    polygons.append(geojson)
  return {"bbox": bbox, "granularity":intscalefactor, "features":polygons}

def load_config(conf_file):
  dbname = 'gis'
  dbuser = 'gis'
  log(syslog.LOG_INFO,"loading config: " + conf_file)
  conff = open(conf_file,"r")
  line = conff.readline()
  while (line != ""):
    line = line.rstrip('\n')
    keyval = line.split("=",1)
    if (keyval[0] == "name"):
      name = keyval[1]
    if (keyval[0] == "tiledir"):
      tiledir = keyval[1]
    if (keyval[0] == "mapfile"):
      mapfile = keyval[1]
    if (keyval[0] == "maxz"):
      maxz = int(keyval[1])
    if (keyval[0] == "dbname"):
      dbname = keyval[1]
    if (keyval[0] == "dbuser"):
      dbuser = keyval[1]
    line = conff.readline()

  conff.close()
  style = MapCSS(0,30)
  style.parse(open("/usr/local/src/svn/openstreetmap/applications/utils/tirex/backend-json/mapink.mapcss","r").read())
  conf = { 'name': name, 'style': style, 'tiledir': tiledir, 'maxz': maxz, 'dbname': dbname, 'dbuser': dbuser }
  log(syslog.LOG_INFO,"config parsed: " + str(conf))
  return conf

def get_tile(x, y, z, conf):
  if z>conf['maxz']:
    return
  style = conf['style']
  callback = "onKothicDataResponse"
  connect_string = "dbname=" + conf['dbname'] + " user=" + conf['dbuser']
  database = psycopg2.connect(connect_string)

  bbox = projections.bbox_by_tile(z+1,x,y,"EPSG:3857")
  
  zoom = z+2
#aaaa = get_vectors(database,bbox,zoom,style,"coastline")
  aaaa = get_vectors(database,bbox,zoom,style,"polygon")
  aaaa["features"].extend(get_vectors(database,bbox,zoom,style,"polygon")["features"])
  aaaa["features"].extend(get_vectors(database,bbox,zoom,style,"line")["features"])
#  aaaa["features"].extend(get_vectors(database,bbox,zoom,style,"point")["features"])

  aaaa = callback+"("+json.dumps(aaaa,True,False,separators=(',', ':'))+",%s,%s,%s);"%(z,x,y)
  return aaaa
