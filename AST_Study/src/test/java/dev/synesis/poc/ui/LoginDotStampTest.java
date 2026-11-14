package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.Ellipse2D;
import java.awt.image.BufferedImage;

/** Compare cached tiny rasters with the original ellipse at normal/Retina device scales. */
public final class LoginDotStampTest {
    public static void main(String[] args) {
        int maxError=0;
        for(int scale:new int[]{1,2})for(Color background:new Color[]{Color.BLACK,Color.WHITE,new Color(0x686868)}) {
            BufferedImage direct=new BufferedImage(40*scale,40*scale,BufferedImage.TYPE_INT_RGB);
            LoginWaveRaster frame=new LoginWaveRaster(40*scale,40*scale);
            BufferedImage cached=frame.image;
            Graphics2D vector=direct.createGraphics(),pixels=cached.createGraphics();
            vector.scale(scale,scale);vector.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            vector.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);
            try(LoginDotStamp stamp=new LoginDotStamp(vector,scale,scale)) {
                for(int level=0;level<=63;level++) {
                    vector.setColor(background);vector.fillRect(0,0,40,40);
                    pixels.setColor(background);pixels.fillRect(0,0,40*scale,40*scale);
                    double envelope=level/63d,radius=1.8*(.7*1.3+(.27*1.8)*envelope)*.9;
                    Color color=new Color(81,81,81,95+(int)Math.round(63*envelope*.3));
                    vector.setColor(color);vector.fill(new Ellipse2D.Double(15-radius,15-radius,2*radius,2*radius));
                    stamp.draw(frame,15,15,radius,color);
                    for(int y=0;y<40*scale;y++)for(int x=0;x<40*scale;x++)for(int channel:new int[]{0,8,16}) {
                        int error=Math.abs(((direct.getRGB(x,y)>>channel)&255)-((cached.getRGB(x,y)>>channel)&255));
                        maxError=Math.max(maxError,error);
                    }
                }
            } finally {vector.dispose();pixels.dispose();}
        }
        if(maxError>2)throw new AssertionError("Dot raster changed appearance: max channel difference "+maxError);
        System.out.println("PASS: original dot geometry/color at 1x/2x; maximum channel difference "+maxError+"/255");
    }
}
