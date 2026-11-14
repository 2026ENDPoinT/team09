package dev.synesis.poc.ui;

import java.awt.*;
import java.util.List;
import static dev.synesis.poc.ui.PlannerStyle.*;
import static dev.synesis.poc.ui.PlannerDialogs.drawText;

/** Shared event surface for the editor preview and actual calendar. Importance never changes its fill. */
final class PlannerEventCard {
    private PlannerEventCard() {}
    static Color background(Color color){
        float[] hsv=Color.RGBtoHSB(color.getRed(),color.getGreen(),color.getBlue(),null);
        return Color.getHSBColor(hsv[0],.045f+.055f*hsv[1],.965f+.02f*hsv[2]);
    }
    static Color accent(Color color){
        float[] hsv=Color.RGBtoHSB(color.getRed(),color.getGreen(),color.getBlue(),null);
        return Color.getHSBColor(hsv[0],Math.max(.26f,Math.min(.50f,hsv[1]*.68f)),.74f+.18f*hsv[2]);
    }
    private static double channel(int value){double c=value/255.0;return c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4);}
    static double luminance(Color color){return .2126*channel(color.getRed())+.7152*channel(color.getGreen())+.0722*channel(color.getBlue());}
    static Color foreground(Color fill){return luminance(fill)>.179?Color.BLACK:Color.WHITE;}
    static Color mix(Color a,Color b,double amount){return new Color((int)Math.round(a.getRed()*(1-amount)+b.getRed()*amount),
        (int)Math.round(a.getGreen()*(1-amount)+b.getGreen()*amount),(int)Math.round(a.getBlue()*(1-amount)+b.getBlue()*amount));}
    static Color secondaryForeground(Color fill){return mix(foreground(fill),fill,.30);}
    static Color chipFill(Color fill){return mix(fill,Color.WHITE,.45);}
    private static Shape cardShape(double x,double y,double width,double height,double radius){
        double r=Math.max(0,Math.min(radius,Math.min(width/2,height/2)));
        var shape=new java.awt.geom.Path2D.Double();
        shape.moveTo(x,y);shape.lineTo(x+width-r,y);
        shape.quadTo(x+width,y,x+width,y+r);
        shape.lineTo(x+width,y+height-r);shape.quadTo(x+width,y+height,x+width-r,y+height);
        shape.lineTo(x,y+height);shape.closePath();return shape;
    }
    static void surface(Graphics2D g,int x,int y,int width,int height,Color color,int radius){
        if(width<=0||height<=0)return;
        Color fill=background(color),stripeColor=accent(color);
        // Square left corners; right corners retain 70% of their previous radius.
        double corner=radius*.7;
        Shape shape=cardShape(x,y,width,height,corner);
        g.setColor(fill);g.fill(shape);
        Graphics2D stripe=(Graphics2D)g.create();stripe.clip(shape);stripe.setColor(stripeColor);
        stripe.fillRect(x,y,4,height);stripe.dispose();
        g.setColor(mix(fill,stripeColor,.15));g.draw(cardShape(x+.5,y+.5,width-1,height-1,Math.max(0,corner-.5)));
    }
    static void paint(Graphics2D graphics,int x,int y,int width,int height,String title,String time,Color accent,List<String> tags){
        Graphics2D g=(Graphics2D)graphics.create();g.translate(x,y);g.clipRect(0,0,width,height);
        boolean roomy=width>=220&&height>=110;int radius=12;
        surface(g,0,0,width,height,accent,radius);
        Color fill=background(accent),text=foreground(fill),timeText=secondaryForeground(fill),chip=chipFill(fill),chipText=foreground(chip);
        int left=roomy?16:12,right=roomy?16:6,top=roomy?12:height<24?0:4;
        int titleSize=roomy?14:height>=70?12:10,titleHeight=roomy?22:height>=70?18:Math.min(14,height);
        if(roomy)drawText(g,title,medium(titleSize),text,left,top,width-left-right);
        else PlannerWeekCalendarSkin.line(g,title,medium(titleSize),text,left,top,width-left-right,titleHeight);
        int timeY=roomy?40:top+titleHeight+1,timeSize=roomy?12:height>=70?10:9,timeHeight=roomy?20:height>=70?16:12;
        if(timeY+timeHeight<=height-3){
            if(roomy)drawText(g,time,regular(timeSize),timeText,left,timeY,width-left-right);
            else PlannerWeekCalendarSkin.line(g,time,regular(timeSize),timeText,left,timeY,width-left-right,timeHeight);
        }
        int tagY=roomy?68:timeY+timeHeight+3,tagHeight=roomy?28:height>=70?20:14,tagSize=roomy?12:height>=70?10:9;
        if(tagY+tagHeight<=height-3){
            int tx=left;for(String tag:tags){int chipWidth=Math.min(roomy?100:Math.max(1,width-left-right),g.getFontMetrics(medium(tagSize)).stringWidth(tag)+(roomy?20:12));
                if(tx+chipWidth>width-(roomy?12:right))break;g.setColor(chip);g.fillRoundRect(tx,tagY,chipWidth,tagHeight,12,12);
                if(roomy)drawText(g,tag,medium(tagSize),chipText,tx+10,tagY+4,chipWidth-20);
                else PlannerWeekCalendarSkin.line(g,tag,medium(tagSize),chipText,tx+6,tagY,chipWidth-12,tagHeight);
                tx+=chipWidth+6;
            }
        }
        g.dispose();
    }
}
