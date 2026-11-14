package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.AffineTransform;
import java.awt.geom.Ellipse2D;
import java.awt.geom.Rectangle2D;
import java.awt.image.BufferedImage;
import java.awt.image.DataBufferInt;

/** Bounded reusable strip: no extra full-screen image during wave/pointer transitions. */
final class LoginWaveRaster {
    final BufferedImage image;
    final int[] pixels;
    final int width,height;
    int contentWidth,contentHeight,originY;
    private final Graphics2D painter,vector;
    private final AffineTransform transform=new AffineTransform();
    private final Ellipse2D.Double dot=new Ellipse2D.Double();
    private final Rectangle2D.Double clip=new Rectangle2D.Double();
    private boolean vectorHintsReady;
    LoginWaveRaster(int width,int height) {
        this.width=width;this.height=height;
        image=new BufferedImage(width,height,BufferedImage.TYPE_INT_RGB);
        pixels=((DataBufferInt)image.getRaster().getDataBuffer()).getData();
        contentWidth=width;contentHeight=height;
        painter=image.createGraphics();painter.setComposite(AlphaComposite.Src);
        painter.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
        vector=image.createGraphics();
    }
    void begin(BufferedImage background) {begin(background,background.getWidth(),background.getHeight());}
    void begin(BufferedImage background,int targetWidth,int targetHeight) {
        beginRegion(background,targetWidth,targetHeight,0,targetHeight);
    }
    void beginRegion(BufferedImage background,int targetWidth,int totalHeight,int y,int stripHeight) {
        if(targetWidth>width || stripHeight>height || targetWidth<1 || stripHeight<1 || y<0 || y+stripHeight>totalHeight)
            throw new IllegalArgumentException("Wave content exceeds its backing strip");
        contentWidth=targetWidth;contentHeight=stripHeight;originY=y;
        if(background.getWidth()==targetWidth && background.getHeight()==totalHeight) {
            // Exposing the background's data buffer disables its managed GPU copy.
            painter.setClip(0,0,targetWidth,stripHeight);painter.drawImage(background,0,-y,null);
        } else {
            painter.setClip(0,0,targetWidth,stripHeight);
            painter.drawImage(background,0,-y,targetWidth,totalHeight,null);
        }
    }
    void beginDots(Graphics2D target,double sx,double sy) {
        if(!vectorHintsReady){vector.setRenderingHints(target.getRenderingHints());vectorHintsReady=true;}
        transform.setTransform(sx,0,0,sy,0,-originY);vector.setTransform(transform);
        clip.setRect(0,originY/sy,contentWidth/sx,contentHeight/sy);vector.setClip(clip);
    }
    void vectorDot(double x,double y,double radius,Color color) {
        vector.setColor(color);dot.setFrame(x-radius,y-radius,radius*2,radius*2);vector.fill(dot);
    }
    void release(){painter.dispose();vector.dispose();image.flush();}
}
