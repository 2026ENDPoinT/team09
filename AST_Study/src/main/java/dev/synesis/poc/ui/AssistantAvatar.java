package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.Path2D;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;

/** Personal assistant pictogram: headset and a small planner, with no internal animation. */
public final class AssistantAvatar {
    private static final AvatarRaster ART=new AvatarRaster(createSprite(),78);
    private AssistantAvatar() {}
    public static void paint(Graphics graphics,double centerX,double centerY,double diameter){
        ART.paint(graphics,centerX,centerY,diameter);
    }
    private static BufferedImage createSprite(){
        BufferedImage image=new BufferedImage(384,384,BufferedImage.TYPE_INT_ARGB_PRE);
        Graphics2D g=image.createGraphics();
        try{
            g.scale(4,4);
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_STROKE_CONTROL,RenderingHints.VALUE_STROKE_PURE);
            Color ink=new Color(0x38516F),accent=new Color(0x557AA8),paper=new Color(0xF7FAFD);
            g.setColor(paper);g.fillOval(14,14,68,68);
            g.setColor(new Color(0xCEDAE8));g.setStroke(new BasicStroke(1));
            g.draw(new java.awt.geom.Ellipse2D.Double(14.5,14.5,67,67));
            g.setStroke(new BasicStroke(2,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
            Path2D shoulders=new Path2D.Double();
            shoulders.moveTo(27,72);shoulders.curveTo(27,61,34,56,42,55);
            shoulders.lineTo(42,51);shoulders.lineTo(54,51);shoulders.lineTo(54,55);
            shoulders.curveTo(62,56,69,61,69,72);shoulders.closePath();
            g.setColor(new Color(0xE4EDF7));g.fill(shoulders);g.setColor(ink);g.draw(shoulders);
            g.drawLine(42,56,48,62);g.drawLine(48,62,54,56);
            Path2D band=new Path2D.Double();
            band.moveTo(31,43);band.lineTo(31,38);band.curveTo(31,27,38,22,48,22);
            band.curveTo(58,22,65,29,65,38);band.lineTo(65,43);
            g.setColor(accent);g.draw(band);
            Path2D head=new Path2D.Double();
            head.moveTo(35,37);head.curveTo(35,28,40,25,48,25);head.curveTo(56,25,61,29,61,37);
            head.lineTo(60,44);head.curveTo(59,51,54,55,48,55);head.curveTo(42,55,37,51,36,44);head.closePath();
            g.setColor(paper);g.fill(head);g.setColor(ink);g.draw(head);
            Path2D hair=new Path2D.Double();
            hair.moveTo(35.5,36);hair.curveTo(41,36,46,33,49,29);hair.curveTo(52,33,56,35,60.5,35);g.draw(hair);
            g.setStroke(new BasicStroke(1.8f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
            g.drawLine(41,41,43,41);g.drawLine(53,41,55,41);
            Path2D smile=new Path2D.Double();smile.moveTo(44,48);smile.quadTo(48,51,52,48);g.draw(smile);
            Shape left=new RoundRectangle2D.Double(29,37,6,11,4,4),right=new RoundRectangle2D.Double(61,37,6,11,4,4);
            g.setColor(new Color(0xD6E3F2));g.fill(left);g.fill(right);g.setColor(accent);g.draw(left);g.draw(right);
            Path2D microphone=new Path2D.Double();microphone.moveTo(64,48);microphone.quadTo(64,55,54,55);g.draw(microphone);
            g.setColor(ink);g.fill(new RoundRectangle2D.Double(49,53,7,4,3,3));
            Shape planner=new RoundRectangle2D.Double(54,57,16,18,3,3);
            g.setColor(Color.WHITE);g.fill(planner);g.setColor(accent);g.draw(planner);
            g.drawLine(58,55,58,60);g.drawLine(66,55,66,60);g.drawLine(55,62,69,62);
            Path2D check=new Path2D.Double();check.moveTo(57,68);check.lineTo(59.5,70.5);check.lineTo(65,65.5);g.draw(check);
        }finally{g.dispose();}
        return image;
    }
}
