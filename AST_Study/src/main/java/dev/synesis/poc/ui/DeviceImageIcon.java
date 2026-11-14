package dev.synesis.poc.ui;

import javax.swing.Icon;
import javax.swing.ImageIcon;
import java.awt.*;
import java.awt.image.BufferedImage;

/** Resample artwork only when its device size changes; retain one bounded variant. */
public final class DeviceImageIcon implements Icon {
    private final BufferedImage source;
    private final int width,height;
    private final boolean averageReduction;
    private BufferedImage raster;
    private int rasterWidth,rasterHeight;
    private double rasterScaleX,rasterScaleY;

    public DeviceImageIcon(BufferedImage source,int width,int height) {
        this(source,width,height,false);
    }
    private DeviceImageIcon(BufferedImage source,int width,int height,boolean averageReduction) {
        this.source=source;this.width=Math.max(1,width);this.height=Math.max(1,height);
        this.averageReduction=averageReduction;
    }
    /** Page thumbnails average source coverage to avoid jagged fine text and bicubic ringing. */
    public static DeviceImageIcon thumbnail(BufferedImage source,int width,int height) {
        return new DeviceImageIcon(source,width,height,true);
    }
    public int getIconWidth(){return width;}
    public int getIconHeight(){return height;}
    public void paintIcon(Component component,Graphics graphics,int x,int y) {
        if(!(graphics instanceof Graphics2D target)) {graphics.drawImage(source,x,y,width,height,null);return;}
        double sx=Math.abs(target.getTransform().getScaleX()),sy=Math.abs(target.getTransform().getScaleY());
        // Rotated/printer transforms keep the original vector-space drawing contract.
        if(sx<=0 || sy<=0 || target.getTransform().getShearX()!=0 || target.getTransform().getShearY()!=0) {
            target.drawImage(source,x,y,width,height,null);return;
        }
        int pw=Math.max(1,(int)Math.ceil(width*sx)),ph=Math.max(1,(int)Math.ceil(height*sy));
        // Avoid allocating a large texture for unusual print/export scales.
        if((long)pw*ph>1_048_576) {target.drawImage(source,x,y,width,height,null);return;}
        if(raster==null || pw!=rasterWidth || ph!=rasterHeight || sx!=rasterScaleX || sy!=rasterScaleY) {
            raster=new BufferedImage(pw,ph,BufferedImage.TYPE_INT_ARGB_PRE);
            Graphics2D image=raster.createGraphics();
            try {
                if(averageReduction&&(pw<source.getWidth()||ph<source.getHeight())) {
                    // Compute once at the actual display resolution; cache it for later paints.
                    Image averaged=new ImageIcon(source.getScaledInstance(pw,ph,Image.SCALE_AREA_AVERAGING)).getImage();
                    image.drawImage(averaged,0,0,null);
                }else {
                    image.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);
                    image.scale(sx,sy);image.drawImage(source,0,0,width,height,null);
                }
            } finally {image.dispose();}
            rasterWidth=pw;rasterHeight=ph;
            rasterScaleX=sx;rasterScaleY=sy;
        }
        Graphics2D g=(Graphics2D)target.create();
        try {g.translate(x,y);g.clipRect(0,0,width,height);g.scale(1/sx,1/sy);g.drawImage(raster,0,0,null);}
        finally {g.dispose();}
    }
}
