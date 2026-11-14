package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;
import java.util.function.Consumer;

/** Alpha-mask only four tiny corners; rectangular content keeps its direct Swing paint path. */
final class RoundedPanelEdges {
    private final BufferedImage[] tiles=new BufferedImage[4],masks=new BufferedImage[4];
    private int edge,pixelWidth,pixelHeight;

    void paint(JComponent panel,Graphics2D target,int radius,Consumer<Graphics2D> content){
        int width=panel.getWidth(),height=panel.getHeight(),size=radius+2;
        Rectangle clip=target.getClipBounds();
        Rectangle[] corners={new Rectangle(0,0,size,size),new Rectangle(width-size,0,size,size),
            new Rectangle(0,height-size,size,size),new Rectangle(width-size,height-size,size,size)};
        boolean cornerDamage=false;
        for(Rectangle corner:corners)if(clip==null||clip.intersects(corner)){cornerDamage=true;break;}
        if(!cornerDamage){content.accept(target);return;}

        // Three simple rectangular strips avoid a full-window shaped clip/span mask.
        paintRegion(target,content,new Rectangle(size,0,width-2*size,height));
        paintRegion(target,content,new Rectangle(0,size,size,height-2*size));
        paintRegion(target,content,new Rectangle(width-size,size,size,height-2*size));
        double sx=Math.hypot(target.getTransform().getScaleX(),target.getTransform().getShearY());
        double sy=Math.hypot(target.getTransform().getShearX(),target.getTransform().getScaleY());
        prepare(size,radius,Math.max(1,(int)Math.ceil(size*sx)),Math.max(1,(int)Math.ceil(size*sy)));
        for(int i=0;i<corners.length;i++){
            Rectangle at=corners[i];if(clip!=null&&!clip.intersects(at))continue;
            Graphics2D raster=tiles[i].createGraphics();
            try{
                raster.setComposite(AlphaComposite.Clear);raster.fillRect(0,0,pixelWidth,pixelHeight);
                raster.setComposite(AlphaComposite.SrcOver);
                raster.scale(pixelWidth/(double)edge,pixelHeight/(double)edge);
                raster.translate(-at.x,-at.y);raster.clip(at);
                content.accept(raster);
            }finally{raster.dispose();}
            Graphics2D alpha=tiles[i].createGraphics();
            try{alpha.setComposite(AlphaComposite.DstIn);alpha.drawImage(masks[i],0,0,null);}
            finally{alpha.dispose();}
            Graphics2D output=(Graphics2D)target.create();
            try{
                output.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
                output.drawImage(tiles[i],at.x,at.y,at.width,at.height,null);
            }finally{output.dispose();}
        }
    }

    private static void paintRegion(Graphics2D target,Consumer<Graphics2D> content,Rectangle region){
        if(region.isEmpty()||!target.hitClip(region.x,region.y,region.width,region.height))return;
        Graphics2D g=(Graphics2D)target.create();
        try{g.clip(region);content.accept(g);}finally{g.dispose();}
    }

    private void prepare(int size,int radius,int pw,int ph){
        // Unusual export scales are bounded; a normal 2x display uses 28x28px tiles.
        pw=Math.min(256,pw);ph=Math.min(256,ph);
        if(edge==size&&pixelWidth==pw&&pixelHeight==ph)return;
        edge=size;pixelWidth=pw;pixelHeight=ph;
        for(int i=0;i<tiles.length;i++){
            if(tiles[i]!=null){tiles[i].flush();masks[i].flush();}
            tiles[i]=new BufferedImage(pw,ph,BufferedImage.TYPE_INT_ARGB_PRE);
            masks[i]=new BufferedImage(pw,ph,BufferedImage.TYPE_INT_ARGB_PRE);
            // Supersample coverage once, not the chat or its text on every frame.
            BufferedImage fine=new BufferedImage(pw*2,ph*2,BufferedImage.TYPE_INT_ARGB_PRE);
            Graphics2D g=fine.createGraphics();
            try{
                g.scale(pw*2d/size,ph*2d/size);g.translate(i%2==0?0:-size,i<2?0:-size);
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(Color.WHITE);g.fill(new RoundRectangle2D.Double(0,0,size*2,size*2,radius*2,radius*2));
            }finally{g.dispose();}
            Graphics2D down=masks[i].createGraphics();
            try{down.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);down.drawImage(fine,0,0,pw,ph,null);}
            finally{down.dispose();fine.flush();}
        }
    }
}
