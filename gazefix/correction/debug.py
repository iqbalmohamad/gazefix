"""Harness-only drawings on a separate copy; no debug arrays on results."""
from __future__ import annotations

import cv2
import numpy as np
from gazefix.correction import geometry as geo, masks


def render_debug(frame, tracking, result, settings, decision, layers):
    canvas=frame.copy()
    details={}
    outcomes={e.side:e for e in result.eyes}
    lines=[f"{result.status.value}: {result.message}",
           f"policy {decision.reason}: {decision.effective_strength:.3f}; correction {result.correction_ms:.3f} ms",
           f"k={settings.eye_model_ratio:g} gain={settings.displacement_gain:g} variant={'C' if settings.iris_layer else 'B'}"]
    for side in ("right","left"):
        eye=getattr(tracking,side+"_eye")
        if eye is None or eye.iris is None: continue
        geometry=geo.derive_eye(eye,tracking.geometry)
        outcome=outcomes.get(side)
        d=np.array(outcome.displacement_px if outcome else (0.,0.))
        roi=geo.roi_for(geometry,d,settings.padding_fraction,settings.edge_px)
        x0,y0,x1,y1=roi
        color=(255,255,0) if side=="right" else (0,255,255)
        opening=np.rint(geometry.opening).astype(np.int32)
        if "contour" in layers: cv2.polylines(canvas,[opening],True,color,1,cv2.LINE_AA)
        source=tuple(np.rint(geometry.iris_center).astype(int))
        destination=tuple(np.rint(geometry.iris_center+d).astype(int))
        if "iris" in layers:
            cv2.circle(canvas,source,int(round(geometry.iris_radius)),(255,255,255),1,cv2.LINE_AA)
            cv2.circle(canvas,destination,int(round(geometry.iris_radius)),(255,0,255),1,cv2.LINE_AA)
            cv2.arrowedLine(canvas,source,destination,(255,0,255),1,cv2.LINE_AA)
        info={"aperture":geometry.aperture,"half_width_px":geometry.half_width_px,
              "iris_radius_px":geometry.iris_radius,"R_px":geometry.half_width_px/settings.eye_model_ratio,"roi":roi}
        if x0>=0 and y0>=0 and x1<=frame.shape[1] and y1<=frame.shape[0] and geo.polygon_area(geometry.opening)>0:
            mask,distance=masks.opening_fields(geometry.opening-(x0,y0),(y1-y0,x1-x0))
            if settings.distance_transform!="precise":
                distance=cv2.distanceTransform(mask,cv2.DIST_L2,3 if settings.distance_transform=="chamfer3" else 5)
            alpha=masks.blend_alpha(mask,distance,settings.edge_px)
            yy,xx=np.nonzero(mask)
            bounds=(int(xx.min()+x0),int(yy.min()+y0),int(xx.max()+x0+1),int(yy.max()+y0+1))
            info.update(mask_area_px=int(mask.sum()),mask_bounds=bounds)
            if result.debug and side in dict(result.debug.rois):
                info["metadata_matches"]=roi==dict(result.debug.rois)[side] and bounds==dict(result.debug.mask_bounds)[side]
                if not info["metadata_matches"]: raise ValueError("debug geometry disagrees with engine metadata")
            if "alpha" in layers:
                for threshold in (.1,.5,.9):
                    contours,_=cv2.findContours((alpha>=threshold).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(canvas,[c+np.array([[[x0,y0]]]) for c in contours],-1,color,1)
            if "warp" in layers:
                mx,my,weight=masks.warp_maps(distance,d,geometry.half_width_px,settings.falloff_fraction,settings.field_guard_px)
                for y in range(0,mask.shape[0],6):
                    for x in range(0,mask.shape[1],6):
                        if weight[y,x]>0:
                            cv2.arrowedLine(canvas,(x+x0,y+y0),(int(round(mx[y,x]+x0)),int(round(my[y,x]+y0))),(0,200,0),1)
        if "roi" in layers: cv2.rectangle(canvas,(x0,y0),(x1-1,y1-1),(150,150,150),1)
        details[side]=info
        lines.append(f"{side}: {outcome.reason if outcome else result.message} d=({d[0]:.2f},{d[1]:.2f}) clamped={outcome.clamped if outcome else False} aperture={geometry.aperture:.3f} hw={geometry.half_width_px:.1f}")
    if "text" in layers:
        for i,line in enumerate(lines):
            cv2.putText(canvas,line,(8,20+i*20),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,0,0),3,cv2.LINE_AA)
            cv2.putText(canvas,line,(8,20+i*20),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1,cv2.LINE_AA)
    return canvas,details
