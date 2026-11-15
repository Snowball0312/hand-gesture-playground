# -*- coding: utf-8 -*-
import json
import cv2
import numpy as np

path = r"C:\Users\21254\Desktop\手势识别交互\projects\hand_3d\textures\china.json"
data = json.load(open(path, encoding="utf-8"))

W, H = 1200, 900
lon_min, lon_max = 73.0, 135.0
lat_min, lat_max = 18.0, 53.5
canvas = np.zeros((H, W, 4), dtype=np.uint8)

def proj(pt):
    lon, lat = pt
    x = (lon - lon_min) / (lon_max - lon_min) * W
    y = (lat_max - lat) / (lat_max - lat_min) * H
    return [int(x), int(y)]

for feat in data["features"]:
    geom = feat["geometry"]
    if geom is None:
        continue
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        for ring in poly:
            pts = np.array([proj(p) for p in ring], dtype=np.int32).reshape(-1, 1, 2)
            cv2.fillPoly(canvas, [pts], (40, 20, 120, 180), cv2.LINE_AA)
            cv2.polylines(canvas, [pts], True, (120, 80, 255, 255), 2, cv2.LINE_AA)

out = r"C:\Users\21254\Desktop\手势识别交互\projects\hand_3d\textures\china_map.png"
ok, buf = cv2.imencode(".png", canvas)
buf.tofile(out)
print("saved", out, canvas.shape)
