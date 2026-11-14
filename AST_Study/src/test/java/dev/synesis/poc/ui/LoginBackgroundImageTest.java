package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.Arrays;
import java.util.concurrent.CancellationException;

/** Fractional cache must preserve old pixels and be reversible for resize/transform fallback. */
public final class LoginBackgroundImageTest {
    public static void main(String[] args) {
        int width=397,height=283;double scale=1.25;
        BufferedImage raw=backdrop(width,height,scale);
        int[] original=raw.getRGB(0,0,raw.getWidth(),raw.getHeight(),null,0,raw.getWidth());
        BufferedImage expected=paint(raw,width,height,scale,false);
        BufferedImage cache=LoginBackgroundImage.cache(raw,width,height,scale,scale);
        if(!(cache instanceof LoginBackgroundImage normalized))throw new AssertionError("Fractional footprint must cache");
        if(normalized.undoBytes()>2*1024*1024)throw new AssertionError("Undo must remain bounded");
        BufferedImage actual=paint(cache,width,height,scale,true);
        equal(expected,actual,"Canonical draw must preserve the existing bicubic result");

        Graphics2D g=actual.createGraphics();
        try {
            g.scale(scale,scale);
            if(!normalized.canCopyTo(g))throw new AssertionError("Aligned scale must reuse cache");
            g.translate(.25,0);
            if(normalized.canCopyTo(g))throw new AssertionError("Fractional device translation must fall back");
            g.setTransform(java.awt.geom.AffineTransform.getScaleInstance(scale,scale));
            g.setComposite(AlphaComposite.SrcOver.derive(.6f));
            if(normalized.canCopyTo(g))throw new AssertionError("Partial alpha must fall back");
        } finally {g.dispose();}
        normalized.restoreRaw();
        if(!Arrays.equals(original,normalized.getRGB(0,0,normalized.getWidth(),normalized.getHeight(),null,0,normalized.getWidth())))
            throw new AssertionError("Fallback must restore every original pixel losslessly");
        normalized.restoreRaw();
        if(normalized.undoBytes()!=0)throw new AssertionError("Fallback must release undo memory");

        BufferedImage integer=backdrop(400,280,2);
        if(LoginBackgroundImage.cache(integer,400,280,2,2)!=integer)throw new AssertionError("Integral footprints must retain original path");
        BufferedImage colored=backdrop(width,height,scale);colored.setRGB(40,40,0xffa0b0c0);
        if(LoginBackgroundImage.cache(colored,width,height,scale,scale)!=colored)throw new AssertionError("Colored backgrounds require original path");
        BufferedImage cancelled=backdrop(width,height,scale);
        Thread.currentThread().interrupt();
        try {LoginBackgroundImage.cache(cancelled,width,height,scale,scale);throw new AssertionError("Cancelled render must stop");}
        catch(CancellationException expectedCancellation) { }
        finally {Thread.interrupted();}
        System.out.println("PASS: fractional pixel identity, bounded reversible fallback, original integer/color paths, cancellation");
    }

    private static BufferedImage backdrop(int width,int height,double scale) {
        BufferedImage image=new BufferedImage((int)Math.ceil(width*scale),(int)Math.ceil(height*scale),BufferedImage.TYPE_INT_RGB);
        for(int y=0;y<image.getHeight();y++)for(int x=0;x<image.getWidth();x++) {
            int gray=(x/3+y/5)%256;image.setRGB(x,y,0xff000000|gray<<16|gray<<8|gray);
        }
        return image;
    }
    private static BufferedImage paint(BufferedImage source,int width,int height,double scale,boolean normalized) {
        BufferedImage image=new BufferedImage(source.getWidth(),source.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();
        try {
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);
            g.scale(scale,scale);
            if(normalized){g.scale(1/scale,1/scale);g.drawImage(source,0,0,null);}
            else g.drawImage(source,0,0,width,height,null);
        } finally {g.dispose();}
        return image;
    }
    private static void equal(BufferedImage a,BufferedImage b,String message) {
        if(!Arrays.equals(a.getRGB(0,0,a.getWidth(),a.getHeight(),null,0,a.getWidth()),b.getRGB(0,0,b.getWidth(),b.getHeight(),null,0,b.getWidth())))
            throw new AssertionError(message);
    }
}
