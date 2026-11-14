package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.*;
import java.util.*;
import java.util.List;

/** Selectable text coordinates from the prepared PDF source index. */
final class PdfTextSelection {
    record Word(int page, int order, String text, float x0, float y0, float x1, float y1) {
        Rectangle bounds(Rectangle pageBounds) {
            int left=pageBounds.x+Math.round(x0*pageBounds.width);
            int top=pageBounds.y+Math.round(y0*pageBounds.height);
            int right=pageBounds.x+Math.round(x1*pageBounds.width);
            int bottom=pageBounds.y+Math.round(y1*pageBounds.height);
            return new Rectangle(left,top,Math.max(1,right-left),Math.max(1,bottom-top));
        }
    }

    private JsonObject document;
    private final Map<Integer,List<Word>> cache=new HashMap<>();
    private Word anchor, extent;
    private boolean dragged;

    void clear() {anchor=null;extent=null;dragged=false;}
    void reset() {clear();document=null;cache.clear();}
    void press(Word word) {anchor=word;extent=word;dragged=false;}
    void drag(Word word) {if(anchor!=null && word!=null) {extent=word;dragged=true;}}
    boolean hasSelection() {return dragged && anchor!=null && extent!=null;}

    List<Word> words(JsonObject index,int page) {
        if(index!=document) {reset();document=index;}
        if(index==null || !index.has("pages") || page<1 || page>index.getAsJsonArray("pages").size())return List.of();
        return cache.computeIfAbsent(page,number -> load(index.getAsJsonArray("pages").get(number-1).getAsJsonObject(),number));
    }

    private static List<Word> load(JsonObject page,int number) {
        List<Word> found=new ArrayList<>();
        append(found,page.getAsJsonArray("words"),number);
        found.sort(Comparator.comparingDouble((Word w)->(w.y0()+w.y1())/2).thenComparingDouble(Word::x0));
        // Small baseline differences must not reorder words across the same line.
        List<List<Word>> lines=new ArrayList<>();
        for(Word word:found) {
            float center=(word.y0()+word.y1())/2;
            if(lines.isEmpty())lines.add(new ArrayList<>());
            else {
                Word first=lines.getLast().getFirst();
                float firstCenter=(first.y0()+first.y1())/2;
                if(center-firstCenter>Math.max(.006f,(first.y1()-first.y0())*.6f))lines.add(new ArrayList<>());
            }
            lines.getLast().add(word);
        }
        List<Word> ordered=new ArrayList<>(found.size());
        for(List<Word> line:lines) {
            line.sort(Comparator.comparingDouble(Word::x0));
            for(Word word:line)ordered.add(new Word(number,ordered.size(),word.text(),word.x0(),word.y0(),word.x1(),word.y1()));
        }
        return List.copyOf(ordered);
    }

    private static void append(List<Word> target,JsonArray items,int page) {
        if(items==null)return;
        for(JsonElement element:items)try {
            JsonObject item=element.getAsJsonObject();
            String text=item.get("text").getAsString();
            JsonArray box=item.getAsJsonArray("bbox");
            if(text.isBlank() || box==null || box.size()!=4)continue;
            float x0=box.get(0).getAsFloat(),y0=box.get(1).getAsFloat();
            float x1=box.get(2).getAsFloat(),y1=box.get(3).getAsFloat();
            if(!Float.isFinite(x0) || !Float.isFinite(y0) || !Float.isFinite(x1) || !Float.isFinite(y1)
                || x0<0 || y0<0 || x0>=x1 || y0>=y1 || x1>1 || y1>1)continue;
            target.add(new Word(page,0,text,x0,y0,x1,y1));
        }catch(RuntimeException ignored) { /* One malformed word cannot disable page selection. */ }
    }

    Word hit(JsonObject index,int page,Rectangle pageBounds,Point point,boolean strict) {
        Word nearest=null;
        long best=Long.MAX_VALUE;
        for(Word word:words(index,page)) {
            Rectangle box=word.bounds(pageBounds);
            int dx=Math.max(box.x-point.x,Math.max(0,point.x-(box.x+box.width)));
            int dy=Math.max(box.y-point.y,Math.max(0,point.y-(box.y+box.height)));
            long score=(long)dx*dx+(long)dy*dy;
            if(score<best) {best=score;nearest=word;}
        }
        return !strict || best<=16?nearest:null;
    }

    boolean selected(Word word) {
        if(!hasSelection())return false;
        Word first=compare(anchor,extent)<=0?anchor:extent, last=first==anchor?extent:anchor;
        return compare(first,word)<=0 && compare(word,last)<=0;
    }

    String text(JsonObject index) {
        if(!hasSelection())return "";
        Word first=compare(anchor,extent)<=0?anchor:extent, last=first==anchor?extent:anchor;
        StringBuilder result=new StringBuilder();
        Word previous=null;
        for(int page=first.page();page<=last.page();page++)for(Word word:words(index,page)) {
            if(compare(word,first)<0 || compare(word,last)>0)continue;
            if(previous!=null) {
                if(word.page()!=previous.page())result.append("\n\n");
                else if((word.y0()+word.y1())/2-(previous.y0()+previous.y1())/2>
                    Math.max(.006f,(previous.y1()-previous.y0())*.6f))result.append('\n');
                else result.append(' ');
            }
            result.append(word.text());previous=word;
        }
        return result.toString();
    }

    private static int compare(Word a,Word b) {
        int page=Integer.compare(a.page(),b.page());
        return page!=0?page:Integer.compare(a.order(),b.order());
    }
}
