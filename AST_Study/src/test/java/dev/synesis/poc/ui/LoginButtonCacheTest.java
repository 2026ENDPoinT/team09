package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import javax.swing.*;

/** Hover is static; press/focus/text/disabled states still invalidate only their cached frame. */
public final class LoginButtonCacheTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try {
            int[] actions={0};LoginPanel panel=new LoginPanel(()->actions[0]++);JButton button=panel.loginButton();button.setSize(360,54);
            if(button.isRolloverEnabled())throw new AssertionError("hover rollover must be disabled");
            Field cache=button.getClass().getDeclaredField("restingFrame");cache.setAccessible(true);
            Method direct=button.getClass().getDeclaredMethod("paintButton",Graphics2D.class);direct.setAccessible(true);
            int maximum=0;
            for(int scale:new int[]{1,2})for(boolean enabled:new boolean[]{true,false})for(boolean pressed:new boolean[]{true,false}) {
                button.setEnabled(enabled);button.getModel().setPressed(pressed);button.setText(enabled?"Google로 계속하기":"로그인 중…");
                BufferedImage expected=new BufferedImage(360*scale,54*scale,BufferedImage.TYPE_INT_RGB),actual=new BufferedImage(360*scale,54*scale,BufferedImage.TYPE_INT_RGB);
                Graphics2D a=graphics(expected,scale),b=graphics(actual,scale);
                direct.invoke(button,a);button.paint(b);a.dispose();b.dispose();
                for(int y=0;y<actual.getHeight();y++)for(int x=0;x<actual.getWidth();x++)for(int channel=0;channel<24;channel+=8)
                    maximum=Math.max(maximum,Math.abs(((actual.getRGB(x,y)>>channel)&255)-((expected.getRGB(x,y)>>channel)&255)));
                Object before=cache.get(button);
                for(int hover=0;hover<12;hover++) {
                    button.getModel().setRollover(hover%2==0);
                    Graphics2D again=graphics(actual,scale);button.paint(again);again.dispose();
                    if(before==null||cache.get(button)!=before)throw new AssertionError("hover rebuilt its frame");
                }
                for(int y=0;y<actual.getHeight();y++)for(int x=0;x<actual.getWidth();x++)
                    if(actual.getRGB(x,y)!=expected.getRGB(x,y) && channelDifference(actual.getRGB(x,y),expected.getRGB(x,y))>2)
                        throw new AssertionError("hover changed button pixels");
            }
            if(maximum>2)throw new AssertionError("button cache changed appearance: "+maximum+"/255");
            button.setEnabled(true);button.getModel().setPressed(false);button.doClick(0);
            if(actions[0]!=1||button.isEnabled()||!button.getText().equals("로그인 중…"))throw new AssertionError("login action state");
            button.doClick(0);if(actions[0]!=1)throw new AssertionError("disabled duplicate click");
            panel.reset();if(!button.isEnabled()||!button.getText().equals("Google로 계속하기"))throw new AssertionError("reset");
            Method release=button.getClass().getDeclaredMethod("releasePaintCache");release.setAccessible(true);release.invoke(button);
            if(cache.get(button)!=null)throw new AssertionError("released button retained its raster");
            System.out.println("PASS: static hover/press/disabled button states at 1x/2x; maximum channel difference "+maximum+"/255; steady frame reuse and release");
        }catch(Exception e){throw new RuntimeException(e);}});
    }
    private static int channelDifference(int a,int b) {
        int max=0;for(int s=0;s<24;s+=8)max=Math.max(max,Math.abs(((a>>s)&255)-((b>>s)&255)));return max;
    }
    private static Graphics2D graphics(BufferedImage image,int scale) {
        Graphics2D g=image.createGraphics();g.scale(scale,scale);g.setColor(new Color(0x686868));g.fillRect(0,0,360,54);
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);return g;
    }
}
