package dev.synesis.poc.ui;

import java.awt.Point;

/** Shared home-assistant/mentor placement, in logical pixels; no painting or timers. */
public final class FloatingChatPlacement {
    private FloatingChatPlacement(){}
    public static Point place(int viewportWidth,int viewportHeight,int width,int height,Point orbCenter,Point anchor){
        return place(viewportWidth,viewportHeight,width,height,orbCenter,anchor,48);
    }
    public static Point place(int viewportWidth,int viewportHeight,int width,int height,Point orbCenter,Point anchor,int orbDiameter){
        double scale=Math.max(1,orbDiameter)/48d;
        int clearance=(int)Math.round(40*scale);
        int x=viewportWidth-width-20,y=Math.max(0,viewportHeight-height-(int)Math.round(96*scale));
        if(anchor!=null){x=anchor.x;y=anchor.y;}
        else if(orbCenter!=null){
            boolean left=orbCenter.x<viewportWidth/2;
            int edgeDistance=left?orbCenter.x:viewportWidth-orbCenter.x;
            double t=Math.max(0,Math.min(1,(100*scale-edgeDistance)/(66*scale)));
            double dock=t*t*(3-2*t);
            int offset=(int)Math.round((44-68*dock)*scale);
            x=left?orbCenter.x+offset:orbCenter.x-offset-width;
            y=orbCenter.y-clearance-height;
            if(y<8&&viewportHeight-orbCenter.y-clearance>orbCenter.y-clearance)y=orbCenter.y+clearance;
        }
        return new Point(clamp(x,8,viewportWidth-width-8),clamp(y,8,viewportHeight-height-8));
    }
    private static int clamp(int value,int minimum,int maximum){return Math.max(0,Math.max(Math.min(minimum,maximum),Math.min(maximum,value)));}
}
