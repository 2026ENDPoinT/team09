package dev.synesis.poc.pdf;

import java.awt.*;
import java.nio.file.*;
import javax.swing.*;

/** Offline overlay geometry/lifecycle only; no app window, store writes or provider. */
public final class HomeAssistantTest {
    private static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception{
        Path temp=Files.createTempDirectory("home-assistant-test-");
        System.setProperty("synesis.dataRoot",temp.resolve("absent-data").toString());
        SwingUtilities.invokeAndWait(()->{
            HomeAssistant overlay=new HomeAssistant();
            try{
                for(Dimension size:new Dimension[]{new Dimension(1120,580),new Dimension(1600,960),new Dimension(500,400)}){
                    overlay.setSize(size);overlay.doLayout();
                    check(!overlay.contains(20,20),"overlay blocks underlying home");
                    check(overlay.contains(size.width-58,size.height-48),"orb misses click target");
                    Component orb=component(overlay,"orb");
                    check(orb.getX()>=0&&orb.getY()>=0,"orb leaves viewport");
                }
                overlay.setHomeVisible(false);
                check(!overlay.contains(442,352),"hidden overlay catches input");
                overlay.setHomeVisible(true);
                java.lang.reflect.Field expanded=HomeAssistant.class.getDeclaredField("expanded");expanded.setAccessible(true);expanded.setBoolean(overlay,true);
                Component card=component(overlay,"card");card.setVisible(true);overlay.doLayout();
                check(card.getWidth()<=468&&card.getHeight()<=288,"card overflows small home");
                check(overlay.contains(card.getX()+10,card.getY()+10),"chat not interactive");
                check(!Files.exists(temp.resolve("absent-data")),"construction writes user data");
                var field=HomeAssistant.class.getDeclaredField("motion");field.setAccessible(true);
                check(!((Timer)field.get(overlay)).isRunning(),"hidden/headless animation running");
            }catch(ReflectiveOperationException e){throw new RuntimeException(e);}
            finally{overlay.close();}
        });
        Files.delete(temp);
        System.out.println("HomeAssistantTest OK (offline geometry/lifecycle)");
    }
    private static Component component(HomeAssistant overlay,String name)throws ReflectiveOperationException{
        var field=HomeAssistant.class.getDeclaredField(name);field.setAccessible(true);return (Component)field.get(overlay);
    }
}
