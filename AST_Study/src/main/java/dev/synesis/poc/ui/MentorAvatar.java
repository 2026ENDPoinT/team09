package dev.synesis.poc.ui;

import javax.swing.Icon;
import java.awt.*;
import java.awt.geom.Path2D;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;

/** A minimal human teacher symbol. Artwork and hover variants are cached, never animated internally. */
final class MentorAvatar {
    static final int SIZE=58,HOVER_SIZE=75;
    private static final BufferedImage SPRITE=createSprite();
    private static final AvatarRaster ART=new AvatarRaster(SPRITE,HOVER_SIZE);
    private static final Icon[] SIZES=new Icon[HOVER_SIZE-SIZE+1];
    static {
        for(int i=0;i<SIZES.length;i++){
            int extent=Math.round((SIZE+i)*96f/68f);
            SIZES[i]=new DeviceImageIcon(SPRITE,extent,extent);
        }
    }
    private MentorAvatar() {}
    static Icon icon(int size){return SIZES[Math.max(0,Math.min(SIZES.length-1,size-SIZE))];}
    static void paint(Graphics graphics,double centerX,double centerY,float hover){
        ART.paint(graphics,centerX,centerY,SIZE+(HOVER_SIZE-SIZE)*(double)hover);
    }

    private static BufferedImage createSprite(){
        // Four times the old linear resolution; enough for Retina and the hover enlargement.
        BufferedImage image=new BufferedImage(384,384,BufferedImage.TYPE_INT_ARGB_PRE);
        Graphics2D g=image.createGraphics();
        try{
            g.scale(4,4);
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_STROKE_CONTROL,RenderingHints.VALUE_STROKE_PURE);
            // Bake a broad ambient shadow and a tighter lower shadow into the sprite once.
            g.setPaint(new RadialGradientPaint(48,52,44,new float[]{0,.66f,.86f,1},
                new Color[]{new Color(18,24,33,80),new Color(18,24,33,80),
                    new Color(18,24,33,32),new Color(18,24,33,0)}));
            g.fillRect(0,0,96,96);
            g.setPaint(new RadialGradientPaint(48,51,37,new float[]{0,.80f,.92f,1},
                new Color[]{new Color(18,24,33,64),new Color(18,24,33,64),
                    new Color(18,24,33,32),new Color(18,24,33,0)}));
            g.fillRect(0,0,96,96);
            g.setColor(new Color(0xFBFCFD));
            g.fillOval(14,14,68,68);
            g.setColor(new Color(0xDCE2E9));g.setStroke(new BasicStroke(1));
            g.draw(new java.awt.geom.Ellipse2D.Double(14.5,14.5,67,67));

            Color ink=new Color(0x3B4959);
            g.setStroke(new BasicStroke(2, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
            Path2D shoulders=new Path2D.Double();
            shoulders.moveTo(28,67);shoulders.curveTo(28,59,35,56,42,55);
            shoulders.lineTo(42,51);shoulders.lineTo(54,51);shoulders.lineTo(54,55);
            shoulders.curveTo(61,56,68,59,68,67);shoulders.closePath();
            g.setColor(new Color(0xE9EEF4));g.fill(shoulders);
            g.setColor(ink);g.draw(shoulders);
            g.drawLine(41,56,48,62);g.drawLine(48,62,55,56);

            // Human proportions, a simple side part and small glasses keep this a pictogram.
            Path2D head=new Path2D.Double();
            head.moveTo(35,37);head.curveTo(35,28,39,24,48,24);
            head.curveTo(57,24,61,29,61,37);head.lineTo(60,43);
            head.curveTo(59,51,54,55,48,55);head.curveTo(42,55,37,51,36,43);
            head.closePath();
            g.setColor(new Color(0xFBFCFD));g.fill(head);
            g.setColor(ink);g.draw(head);
            Path2D hair=new Path2D.Double();
            hair.moveTo(35.5,36);hair.curveTo(41,36,46,33,49,29);
            hair.curveTo(51,33,56,35,60.5,35);g.draw(hair);

            // Simple mortarboard and fixed tassel, drawn once with the teacher artwork.
            Path2D capBand=new Path2D.Double();
            capBand.moveTo(36,26);capBand.lineTo(60,26);capBand.lineTo(60,33);
            capBand.quadTo(48,29,36,33);capBand.closePath();
            g.setColor(ink);g.fill(capBand);
            Path2D cap=new Path2D.Double();
            cap.moveTo(27,25);cap.lineTo(48,17);cap.lineTo(69,25);cap.lineTo(48,33);cap.closePath();
            g.setColor(new Color(0x526173));g.fill(cap);g.setColor(ink);g.draw(cap);
            Path2D cord=new Path2D.Double();
            cord.moveTo(48,25);cord.lineTo(66,28);cord.lineTo(66,38);
            g.setColor(new Color(0x8B9BB0));
            g.setStroke(new BasicStroke(1.5f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));g.draw(cord);
            Path2D tassel=new Path2D.Double();
            tassel.moveTo(66,37);tassel.lineTo(64.5,42);tassel.quadTo(66,43,67.5,42);tassel.closePath();
            g.setColor(ink);g.fill(tassel);

            g.setStroke(new BasicStroke(1.7f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
            g.draw(new RoundRectangle2D.Double(37.5,38,8.5,6.5,3,3));
            g.draw(new RoundRectangle2D.Double(50,38,8.5,6.5,3,3));
            g.drawLine(46,40,50,40);
            g.drawLine(45,49,51,49);

            // A fixed reflection on the viewer's right lens, baked into the cached artwork.
            Path2D glint=new Path2D.Double();
            glint.moveTo(58,32.7);glint.quadTo(58.9,37.1,62.8,38.2);
            glint.quadTo(58.9,39.3,58,43.7);glint.quadTo(57.1,39.3,53.2,38.2);
            glint.quadTo(57.1,37.1,58,32.7);glint.closePath();
            g.setColor(new Color(0xFBFCFD));
            g.setStroke(new BasicStroke(2.6f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
            g.draw(glint);
            g.setColor(new Color(0x526A88));g.fill(glint);

            Path2D book=new Path2D.Double();
            book.moveTo(28,61);book.quadTo(39,59,48,64);book.quadTo(57,59,68,61);
            book.lineTo(68,73);book.quadTo(57,71,48,76);book.quadTo(39,71,28,73);
            book.closePath();
            g.setColor(Color.WHITE);g.fill(book);
            g.setColor(ink);g.setStroke(new BasicStroke(2,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
            g.draw(book);g.drawLine(48,64,48,75);
        }finally{g.dispose();}
        return image;
    }
}
