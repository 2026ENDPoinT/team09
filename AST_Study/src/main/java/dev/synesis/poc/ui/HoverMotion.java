package dev.synesis.poc.ui;

/** Shared deceleration from the home assistant; no clock or listeners of its own. */
public final class HoverMotion {
    private HoverMotion() {}
    public static float advance(float value,boolean hovered,float seconds){
        float target=hovered?1:0;
        float next=value+(target-value)*Math.min(1,seconds*12);
        return Math.abs(target-next)<.001f?target:next;
    }
}
