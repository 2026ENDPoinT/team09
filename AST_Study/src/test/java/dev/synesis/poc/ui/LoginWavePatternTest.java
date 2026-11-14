package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.*;
import java.awt.image.BufferedImage;
import java.util.Arrays;

/** Compare repeated-texture dots with individual ellipses, including contrast boundaries and DPI. */
public final class LoginWavePatternTest {
    public static void main(String[] args)throws Exception {
        var inkMethod=LoginPanel.class.getDeclaredMethod("dotColors");inkMethod.setAccessible(true);
        var lightMethod=LoginPanel.class.getDeclaredMethod("lightDotColors");lightMethod.setAccessible(true);
        Color[] ink=(Color[])inkMethod.invoke(null),light=(Color[])lightMethod.invoke(null);
        int maximum=0;
        for(int scale:new int[]{1,2}) {
            int width=610,height=405,columns=(width+7)/23,rows=(height+7)/23;
            boolean[] dark=new boolean[columns*rows];double[] responses=new double[columns+rows];
            for(int row=0;row<rows;row++)for(int col=0;col<columns;col++)dark[row*columns+col]=col<columns-row/2-4;
            try(LoginWavePattern pattern=new LoginWavePattern(columns,rows,dark,scale,scale,ink,light)) {
                for(int phase=0;phase<20;phase++) {
                    BufferedImage expected=new BufferedImage(width*scale,height*scale,BufferedImage.TYPE_INT_RGB);
                    BufferedImage actual=new BufferedImage(width*scale,height*scale,BufferedImage.TYPE_INT_RGB);
                    Graphics2D a=expected.createGraphics(),b=actual.createGraphics();
                    a.scale(scale,scale);b.scale(scale,scale);a.setColor(new Color(0x686868));b.setColor(new Color(0x686868));
                    a.fillRect(0,0,width,height);b.fillRect(0,0,width,height);
                    a.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    for(int d=0;d<responses.length;d++)responses[d]=LoginPanel.diagonalWave((d-rows)*23,0,phase*9.1);
                    for(int row=0;row<rows;row++)for(int col=0;col<columns;col++) {
                        double response=responses[col-row+rows],radius=1.8*(.7*1.3+(.27*1.8)*response)*.9;
                        a.setColor((dark[row*columns+col]?light:ink)[(int)Math.round(63*response*.3)]);
                        a.fill(new Ellipse2D.Double(15+23*col-radius,15+23*row-radius,2*radius,2*radius));
                    }
                    pattern.paint(b,responses);a.dispose();b.dispose();
                    for(int y=0;y<actual.getHeight();y++)for(int x=0;x<actual.getWidth();x++)for(int channel:new int[]{0,8,16})
                        maximum=Math.max(maximum,Math.abs(((expected.getRGB(x,y)>>channel)&255)-((actual.getRGB(x,y)>>channel)&255)));
                }
                BufferedImage image=new BufferedImage(width*scale,height*scale,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.scale(scale,scale);
                Arrays.fill(responses,.6);pattern.paint(g,responses);int before=pattern.rasterizedTiles();
                for(int i=0;i<30;i++)pattern.paint(g,responses);g.dispose();
                if(pattern.rasterizedTiles()!=before)throw new AssertionError("unchanged pattern rasterized again");
                if(pattern.maximumBytes()>3_000_000)throw new AssertionError("unbounded texture cache");
            }
        }
        if(maximum>2)throw new AssertionError("wave pattern changed appearance: "+maximum+"/255");
        System.out.println("PASS: repeated textures retain dot positions/contrast at 1x/2x; maximum channel error "+maximum+"/255; stable frames reuse tiles");
    }
}
