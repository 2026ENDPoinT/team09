package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.Ellipse2D;
import java.awt.image.BufferedImage;
import java.awt.image.DataBufferInt;

/** One tiny device-resolution dot per diagonal/contrast. Reuses its raster and painter. */
final class LoginDotStamp implements AutoCloseable {
    private final BufferedImage image;
    private final Graphics2D painter;
    private final Ellipse2D.Double shape=new Ellipse2D.Double();
    private final int scaleX,scaleY;
    private double radius=Double.NaN;
    private Color color;
    private final int[] offsetsX,offsetsY,values;
    private int count;
    LoginDotStamp(Graphics2D target,int sx,int sy) {
        scaleX=sx;scaleY=sy;
        image=new BufferedImage(8*sx,8*sy,BufferedImage.TYPE_INT_ARGB_PRE);
        offsetsX=new int[image.getWidth()*image.getHeight()];offsetsY=new int[offsetsX.length];values=new int[offsetsX.length];
        painter=image.createGraphics();painter.setRenderingHints(target.getRenderingHints());painter.scale(sx,sy);
    }
    void draw(LoginWaveRaster frame,int x,int y,double nextRadius,Color nextColor) {
        if(radius!=nextRadius || !nextColor.equals(color)) {
            painter.setComposite(AlphaComposite.Clear);painter.fillRect(0,0,8,8);
            painter.setComposite(AlphaComposite.SrcOver);painter.setColor(nextColor);
            shape.setFrame(4-nextRadius,4-nextRadius,nextRadius*2,nextRadius*2);painter.fill(shape);
            radius=nextRadius;color=nextColor;count=0;
            int[] pixels=((DataBufferInt)image.getRaster().getDataBuffer()).getData();
            for(int py=0;py<image.getHeight();py++)for(int px=0;px<image.getWidth();px++) {
                int pixel=pixels[py*image.getWidth()+px];
                if((pixel>>>24)==0)continue;
                offsetsX[count]=px-4*scaleX;offsetsY[count]=py-4*scaleY;values[count++]=pixel;
            }
        }
        int cx=x*scaleX,cy=y*scaleY-frame.originY;
        for(int i=0;i<count;i++) {
            int px=cx+offsetsX[i],py=cy+offsetsY[i];
            if(px<0 || px>=frame.contentWidth || py<0 || py>=frame.contentHeight)continue;
            int offset=py*frame.width+px,destination=frame.pixels[offset],source=values[i],inverse=255-(source>>>24);
            int r=((source>>>16)&255)+(((destination>>>16)&255)*inverse+127)/255;
            int g=((source>>>8)&255)+(((destination>>>8)&255)*inverse+127)/255;
            int b=(source&255)+((destination&255)*inverse+127)/255;
            frame.pixels[offset]=(r<<16)|(g<<8)|b;
        }
    }
    @Override public void close(){painter.dispose();image.flush();}
}
