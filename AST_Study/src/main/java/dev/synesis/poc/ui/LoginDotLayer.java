package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.AffineTransform;
import java.awt.geom.Rectangle2D;
import java.awt.image.BufferedImage;
import java.util.function.BiConsumer;

/** Batch pointer dots into one bounded opaque tile instead of many screen-side AA composites. */
final class LoginDotLayer implements AutoCloseable {
    private static final int TILE=512;
    private final BufferedImage image=new BufferedImage(TILE,TILE,BufferedImage.TYPE_INT_RGB);
    private final Graphics2D painter=image.createGraphics();

    static boolean supported(Graphics2D target,BufferedImage background,int width,int height,double sx,double sy) {
        AffineTransform t=target.getTransform();
        return sx>=1 && sy>=1 && sx==Math.rint(sx) && sy==Math.rint(sy)
            && t.getShearX()==0 && t.getShearY()==0
            && t.getTranslateX()==Math.rint(t.getTranslateX()) && t.getTranslateY()==Math.rint(t.getTranslateY())
            && background.getType()==BufferedImage.TYPE_INT_RGB
            && background.getWidth()==width*sx && background.getHeight()==height*sy
            && target.getComposite() instanceof AlphaComposite alpha
            && alpha.getRule()==AlphaComposite.SRC_OVER && alpha.getAlpha()==1;
    }

    void paint(Graphics2D target,BufferedImage background,Rectangle clip,double sx,double sy,
               BiConsumer<Graphics2D,Rectangle> dots) {
        int left=Math.max(0,(int)Math.floor(clip.x*sx)),top=Math.max(0,(int)Math.floor(clip.y*sy));
        int right=Math.min(background.getWidth(),(int)Math.ceil(clip.getMaxX()*sx));
        int bottom=Math.min(background.getHeight(),(int)Math.ceil(clip.getMaxY()*sy));
        Graphics2D pixels=(Graphics2D)target.create();
        try {
            pixels.scale(1/sx,1/sy);
            for(int y=top;y<bottom;y+=TILE)for(int x=left;x<right;x+=TILE) {
                int width=Math.min(TILE,right-x),height=Math.min(TILE,bottom-y);
                painter.setTransform(new AffineTransform());painter.setClip(0,0,width,height);
                painter.setComposite(AlphaComposite.Src);painter.drawImage(background,-x,-y,null);
                painter.setRenderingHints(target.getRenderingHints());
                painter.setTransform(new AffineTransform(sx,0,0,sy,-x,-y));
                painter.setClip(new Rectangle2D.Double(x/sx,y/sy,width/sx,height/sy));
                painter.setComposite(AlphaComposite.SrcOver);
                Rectangle logical=new Rectangle((int)Math.floor(x/sx),(int)Math.floor(y/sy),
                    (int)Math.ceil(width/sx),(int)Math.ceil(height/sy));
                dots.accept(painter,logical);
                pixels.drawImage(image,x,y,x+width,y+height,0,0,width,height,null);
            }
        }finally{pixels.dispose();}
    }
    int backingBytes(){return TILE*TILE*4;}
    @Override public void close(){painter.dispose();image.flush();}
}
