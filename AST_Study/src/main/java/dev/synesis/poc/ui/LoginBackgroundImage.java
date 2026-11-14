package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.AffineTransform;
import java.awt.image.BufferedImage;
import java.awt.image.WritableRaster;
import java.awt.print.PrinterGraphics;
import java.io.ByteArrayOutputStream;
import java.util.concurrent.CancellationException;

/** Cache the existing bicubic result, with a small lossless undo stream for live resize/fallback. */
final class LoginBackgroundImage extends BufferedImage {
    private static final int MAX_UNDO_BYTES=2*1024*1024;
    private static final long MAX_PIXELS=16L*1024*1024;
    private final double scaleX,scaleY;
    private byte[] undo;

    private LoginBackgroundImage(int width,int height,double sx,double sy){
        super(width,height,BufferedImage.TYPE_INT_ARGB_PRE);scaleX=sx;scaleY=sy;
    }
    static BufferedImage cache(BufferedImage raw,int width,int height,double sx,double sy){
        double paintedWidth=width*sx,paintedHeight=height*sy;
        if(sx<1||sy<1||!Double.isFinite(sx)||!Double.isFinite(sy)
                ||paintedWidth==Math.rint(paintedWidth)&&paintedHeight==Math.rint(paintedHeight)
                ||(long)raw.getWidth()*raw.getHeight()>MAX_PIXELS
                ||raw.getType()!=BufferedImage.TYPE_INT_RGB)return raw;
        LoginBackgroundImage result=new LoginBackgroundImage(raw.getWidth(),raw.getHeight(),sx,sy);
        Graphics2D g=result.createGraphics();
        try{
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);
            g.scale(sx,sy);g.drawImage(raw,0,0,width,height,null);
        }finally{g.dispose();}
        ByteArrayOutputStream encoded=new ByteArrayOutputStream();
        int[] original=new int[raw.getWidth()],painted=new int[raw.getWidth()];int previous=-1;
        WritableRaster a=raw.getRaster(),b=result.getRaster();
        for(int y=0;y<raw.getHeight();y++){
            if((y&31)==0&&Thread.currentThread().isInterrupted()){result.flush();throw new CancellationException();}
            a.getDataElements(0,y,raw.getWidth(),1,original);b.getDataElements(0,y,raw.getWidth(),1,painted);
            for(int x=0;x<original.length;x++){
                int old=original[x]|0xff000000;
                if(old==painted[x])continue;
                int gray=old&255;
                // Colored future backdrops retain the original path instead of using this gray-only undo codec.
                if((old>>>8&255)!=gray||(old>>>16&255)!=gray){result.flush();return raw;}
                int position=y*raw.getWidth()+x,gap=position-previous-1;
                while(gap>=128){encoded.write((gap&127)|128);gap>>>=7;}
                encoded.write(gap);encoded.write(gray);previous=position;
                if(encoded.size()>MAX_UNDO_BYTES){result.flush();return raw;}
            }
        }
        result.undo=encoded.toByteArray();raw.flush();return result;
    }
    boolean canCopyTo(Graphics2D graphics){
        if(undo==null||graphics instanceof PrinterGraphics)return false;
        AffineTransform t=graphics.getTransform();
        Composite c=graphics.getComposite();
        return t.getScaleX()==scaleX&&t.getScaleY()==scaleY
            &&t.getShearX()==0&&t.getShearY()==0
            &&t.getTranslateX()==Math.rint(t.getTranslateX())&&t.getTranslateY()==Math.rint(t.getTranslateY())
            &&c instanceof AlphaComposite alpha&&alpha.getRule()==AlphaComposite.SRC_OVER&&alpha.getAlpha()==1;
    }
    void restoreRaw(){
        if(undo==null)return;
        WritableRaster raster=getRaster();int[] row=new int[getWidth()];int previous=-1,activeRow=-1,index=0;
        while(index<undo.length){
            int gap=0,shift=0,value;
            do{value=undo[index++]&255;gap|=(value&127)<<shift;shift+=7;}while((value&128)!=0);
            int position=previous+gap+1,y=position/getWidth(),x=position%getWidth(),gray=undo[index++]&255;
            if(y!=activeRow){
                if(activeRow>=0)raster.setDataElements(0,activeRow,getWidth(),1,row);
                raster.getDataElements(0,y,getWidth(),1,row);activeRow=y;
            }
            row[x]=0xff000000|gray<<16|gray<<8|gray;previous=position;
        }
        if(activeRow>=0)raster.setDataElements(0,activeRow,getWidth(),1,row);
        undo=null;
    }
    int undoBytes(){return undo==null?0:undo.length;}
}
