package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.Ellipse2D;
import java.awt.image.*;
import java.util.*;
import java.util.List;

/** One narrow dot atlas per frame, reused by fixed row runs. No full-screen upload or per-dot drawing. */
final class LoginWavePattern implements AutoCloseable {
    private static final int COLORS=20,RADII=8,STEP=23,ORIGIN=15,STAMP=8;
    private record Run(int row,int first,int last,boolean light) {}
    private final int scaleX,scaleY;
    private final Color[][] palettes;
    private final int[][][][] masks=new int[2][COLORS][RADII][];
    private final BufferedImage stamp;
    private final Graphics2D stampPainter;
    private final Ellipse2D.Double dot=new Ellipse2D.Double();
    private Run[] runs;
    private int diagonals,rows,rasterizedTiles;
    private BufferedImage atlas;
    private int[] pixels;
    private BufferedImage managedAtlas;
    private Graphics2D managedPainter;

    LoginWavePattern(int columns,int rows,boolean[] dark,int sx,int sy,Color[] ink,Color[] light) {
        scaleX=sx;scaleY=sy;palettes=new Color[][]{ink.clone(),light.clone()};
        stamp=new BufferedImage(STAMP*sx,STAMP*sy,BufferedImage.TYPE_INT_ARGB_PRE);
        stampPainter=stamp.createGraphics();stampPainter.scale(sx,sy);
        stampPainter.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
        configure(columns,rows,dark);
    }
    void configure(int columns,int rows,boolean[] dark) {
        this.rows=rows;diagonals=columns+rows;
        List<Run> next=new ArrayList<>();
        for(int row=0;row<rows;row++)for(int col=0;col<columns;) {
            int first=col;boolean light=dark[row*columns+col++];
            while(col<columns&&dark[row*columns+col]==light)col++;
            next.add(new Run(row,first,col-1,light));
        }
        runs=next.toArray(Run[]::new);
        int width=((Math.max(1,(diagonals-1)*STEP+STAMP)*scaleX+127)/128)*128;
        if(atlas==null||atlas.getWidth()<width||atlas.getWidth()>width*2) {
            if(atlas!=null)atlas.flush();releaseDevice();
            atlas=new BufferedImage(width,2*STAMP*scaleY,BufferedImage.TYPE_INT_ARGB_PRE);
            pixels=((DataBufferInt)atlas.getRaster().getDataBuffer()).getData();
        }
    }
    private int[] mask(int contrast,int color,int level) {
        int[] cached=masks[contrast][color][level];if(cached!=null)return cached;
        double first=Math.max(0,(color-.5)/18.9),last=Math.min(1,(color+.5)/18.9);
        double response=first+(last-first)*level/(RADII-1),radius=1.8*(.7*1.3+(.27*1.8)*response)*.9;
        stampPainter.setComposite(AlphaComposite.Clear);stampPainter.fillRect(0,0,STAMP,STAMP);
        stampPainter.setComposite(AlphaComposite.SrcOver);stampPainter.setColor(palettes[contrast][color]);
        dot.setFrame(4-radius,4-radius,radius*2,radius*2);stampPainter.fill(dot);
        rasterizedTiles++;
        return masks[contrast][color][level]=((DataBufferInt)stamp.getRaster().getDataBuffer()).getData().clone();
    }
    void paint(Graphics2D graphics,double[] responses) {
        Arrays.fill(pixels,0);int stride=atlas.getWidth(),stampWidth=STAMP*scaleX,stampHeight=STAMP*scaleY;
        for(int diagonal=0;diagonal<diagonals;diagonal++) {
            double response=Math.max(0,Math.min(1,responses[diagonal]));int color=(int)Math.round(18.9*response);
            double first=Math.max(0,(color-.5)/18.9),last=Math.min(1,(color+.5)/18.9);
            int level=Math.max(0,Math.min(RADII-1,(int)Math.round((response-first)/(last-first)*(RADII-1))));
            for(int contrast=0;contrast<2;contrast++) {
                int[] glyph=mask(contrast,color,level);int x=diagonal*STEP*scaleX,y=contrast*stampHeight;
                for(int line=0;line<stampHeight;line++)System.arraycopy(glyph,line*stampWidth,pixels,(y+line)*stride+x,stampWidth);
            }
        }
        GraphicsConfiguration next=graphics.getDeviceConfiguration();
        boolean accelerated=next!=null&&next.getDevice().getType()==GraphicsDevice.TYPE_RASTER_SCREEN
            &&next.getImageCapabilities().isAccelerated();
        if(accelerated) {
            if(managedAtlas==null) {
                // Keep this image trackable: the CPU backing array belongs only
                // to 'atlas'. Repeated row blits reuse one managed GPU texture.
                managedAtlas=new BufferedImage(atlas.getWidth(),atlas.getHeight(),BufferedImage.TYPE_INT_ARGB_PRE);
                managedAtlas.setAccelerationPriority(1f);
                managedPainter=managedAtlas.createGraphics();managedPainter.setComposite(AlphaComposite.Src);
            }
            managedPainter.drawImage(atlas,0,0,null);drawRows(graphics,managedAtlas);return;
        }
        drawRows(graphics,atlas);
    }
    private void drawRows(Graphics2D graphics,Image source) {
        for(Run run:runs) {
            int diagonal=run.first()-run.row()+rows,width=(run.last()-run.first())*STEP+STAMP;
            int x=ORIGIN-4+run.first()*STEP,y=ORIGIN-4+run.row()*STEP;
            int sourceX=diagonal*STEP*scaleX,sourceY=run.light()?STAMP*scaleY:0;
            if(graphics.hitClip(x,y,width,STAMP))graphics.drawImage(source,x,y,x+width,y+STAMP,
                sourceX,sourceY,sourceX+width*scaleX,sourceY+STAMP*scaleY,null);
        }
    }
    int rasterizedTiles(){return rasterizedTiles;}
    long maximumBytes(){return 2L*atlas.getWidth()*atlas.getHeight()*4+2L*COLORS*RADII*STAMP*STAMP*scaleX*scaleY*4;}
    private void releaseDevice(){if(managedPainter!=null){managedPainter.dispose();managedPainter=null;}if(managedAtlas!=null){managedAtlas.flush();managedAtlas=null;}}
    @Override public void close(){releaseDevice();stampPainter.dispose();stamp.flush();atlas.flush();}
}
