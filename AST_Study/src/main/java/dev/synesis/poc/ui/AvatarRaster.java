package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.AffineTransform;
import java.awt.image.BufferedImage;

/** One maximum-size device texture; hover only changes its fractional destination transform. */
final class AvatarRaster {
    private final BufferedImage source;
    private final double maxExtent;
    private BufferedImage raster;
    AvatarRaster(BufferedImage source,double maxDiameter){
        this.source=source;maxExtent=maxDiameter*96/68;
    }
    void paint(Graphics graphics,double centerX,double centerY,double diameter){
        double extent=diameter*96/68;
        if(!(graphics instanceof Graphics2D target)){
            graphics.drawImage(source,(int)Math.round(centerX-extent/2),(int)Math.round(centerY-extent/2),
                (int)Math.round(extent),(int)Math.round(extent),null);return;
        }
        AffineTransform device=target.getTransform();
        double sx=Math.hypot(device.getScaleX(),device.getShearY()),sy=Math.hypot(device.getShearX(),device.getScaleY());
        int width=Math.min(source.getWidth(),Math.max(1,(int)Math.ceil(maxExtent*sx)));
        int height=Math.min(source.getHeight(),Math.max(1,(int)Math.ceil(maxExtent*sy)));
        if(raster==null||raster.getWidth()!=width||raster.getHeight()!=height){
            raster=new BufferedImage(width,height,BufferedImage.TYPE_INT_ARGB_PRE);
            Graphics2D cache=raster.createGraphics();
            try{cache.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);
                cache.drawImage(source,0,0,width,height,null);
            }finally{cache.dispose();}
        }
        Graphics2D g=(Graphics2D)target.create();
        try{
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            AffineTransform placement=AffineTransform.getTranslateInstance(centerX-extent/2,centerY-extent/2);
            placement.scale(extent/raster.getWidth(),extent/raster.getHeight());
            g.drawImage(raster,placement,null);
        }finally{g.dispose();}
    }
}
