package dev.synesis.poc.pdf;

import org.apache.pdfbox.pdmodel.*;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.pdmodel.font.*;
import org.apache.pdfbox.pdmodel.graphics.image.LosslessFactory;
import com.google.gson.*;
import dev.synesis.poc.UiFonts;
import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.datatransfer.*;
import java.awt.dnd.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.io.File;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/** Synthetic public-domain fixtures; offscreen UI checks. Never records or calls an AI service. */
public final class PdfSmokeTest {
    static final Path ROOT=Path.of("build","pdf-tests");
    public static void main(String[] args)throws Exception {
        if(args.length>0 && args[0].equals("--summary-numbering")) {
            SwingUtilities.invokeAndWait(()->{
                try(PdfWorkspace workspace=new PdfWorkspace(false,ROOT.resolve("viewer-cache"))) {
                    var render=PdfWorkspace.class.getDeclaredMethod("summaryBlock",JsonObject.class,String.class,boolean.class,Map.class);
                    render.setAccessible(true);
                    JsonObject part=JsonParser.parseString("{\"title\":\"함수 호출에 따른 실행 흐름\",\"body\":\"설명\",\"easyExplanation\":\"쉬운 설명\"}").getAsJsonObject();
                    JsonObject block=new JsonObject();
                    JsonArray parts=new JsonArray();parts.add(part);block.add("parts",parts);
                    String single=(String)render.invoke(workspace,block,"numbering-single",false,Map.of());
                    if(!single.contains("함수 호출에 따른 실행 흐름") || single.contains("1. 함수 호출에 따른 실행 흐름"))
                        throw new AssertionError("A sole explanation must have no numeric prefix");
                    parts.add(part.deepCopy());
                    String multiple=(String)render.invoke(workspace,block,"numbering-multiple",false,Map.of());
                    if(!multiple.contains("1. 함수 호출에 따른 실행 흐름") || !multiple.contains("2. 함수 호출에 따른 실행 흐름"))
                        throw new AssertionError("Two explanations must keep numeric prefixes");
                } catch(Exception error) {throw new RuntimeException(error);}
            });
            return;
        }
        JsonObject recovery=JsonParser.parseString("""
            {"kind":"ai_generated","processingComplete":true,
             "documentId":"doc","sourceFingerprint":"fingerprint"}
            """).getAsJsonObject();
        if(!PdfWorkspace.recoverableGeneration(recovery,"doc","fingerprint"))
            throw new AssertionError("A completed result must survive publication failure");
        if(PdfWorkspace.recoverableGeneration(recovery,"other","fingerprint")
                || PdfWorkspace.recoverableGeneration(recovery,"doc","stale"))
            throw new AssertionError("Recovery must match the current source");
        recovery.addProperty("processingComplete",false);
        if(PdfWorkspace.recoverableGeneration(recovery,"doc","fingerprint"))
            throw new AssertionError("Incomplete work must not be shown as complete");
        recovery.addProperty("kind","partial");
        if(!PdfWorkspace.recoverableGeneration(recovery,"doc","fingerprint"))
            throw new AssertionError("Partial checkpoints must remain recoverable");
        if(args.length>0 && args[0].equals("--recovery"))return;
        Files.createDirectories(ROOT); fixtures();
        if(args.length>0 && args[0].equals("--fixtures"))return;
        SmoothScrollPaneTest.run();
        StepFlowTest.run();
        JsonObject emptyStudy=JsonParser.parseString("{\"title\":\"학습 내용 없음\",\"evidence\":[],\"visualPages\":[]}").getAsJsonObject();
        if(!PdfWorkspace.isEmptyStudyPlaceholder(emptyStudy))throw new AssertionError("Empty study section should be hidden");
        emptyStudy.add("evidence",JsonParser.parseString("[{\"page\":1}]").getAsJsonArray());
        if(PdfWorkspace.isEmptyStudyPlaceholder(emptyStudy))throw new AssertionError("Cited study section should remain visible");
        testPdfTextSelection();
        if(!PdfWorkspace.formatElapsed(1_500_000_000L).equals("1.5초")
            || !PdfWorkspace.formatElapsed(125_000_000_000L).equals("2분 5초")
            || !PdfWorkspace.formatElapsed(3_665_000_000_000L).equals("1시간 1분 5초"))
            throw new AssertionError("Task elapsed-time formatting");
        try(PdfSource pdf=PdfSource.open(ROOT.resolve("text.pdf"),ROOT.resolve("viewer-cache"))) {
            if(pdf.count!=3)throw new AssertionError("Page count");
            BufferedImage rendered=pdf.render(2,1); if(rendered.getWidth()<500)throw new AssertionError("Render");
            ImageIO.write(rendered,"png",ROOT.resolve("page-2.png").toFile());
            JsonObject lensIndex=JsonParser.parseString("""
                {"pages":[{"imageRegions":[{"bbox":[0.1,0.2,0.8,0.7]}],
                  "slideLensRegions":[{"regionId":"sl1-p1-image-a1b2c3d4e5f6","legacyId":"p1-image-0",
                    "kind":"image","bbox":[0.1,0.2,0.8,0.7],"sourceIndex":0}]}, {}, {}]}
                """).getAsJsonObject();
            JsonObject lens=JsonParser.parseString("""
                {"moduleId":"synesis.slide-lens","schemaVersion":1,"regionId":"sl1-p1-image-a1b2c3d4e5f6",
                 "page":1,"kind":"image","bbox":[0.1,0.2,0.8,0.7]}
                """).getAsJsonObject();
            SlideLens.Request request=SlideLens.resolve(lens,lensIndex);
            if(request==null)throw new AssertionError("Known region rejected");
            BufferedImage crop=SlideLens.crop(pdf,request);
            if(crop.getWidth()>=pdf.render(1,2).getWidth() || crop.getHeight()>=pdf.render(1,2).getHeight())
                throw new AssertionError("SlideLens must crop a proper subset of its PDF page");
            lens.getAsJsonArray("bbox").set(0,new JsonPrimitive(.2));
            if(SlideLens.resolve(lens,lensIndex)!=null)throw new AssertionError("Model-supplied coordinates bypassed PDF index");
            lens.add("bbox",JsonParser.parseString("[0.1,0.2,0.8,0.7]").getAsJsonArray());
            lens.addProperty("regionId","p1-image-0");
            if(SlideLens.resolve(lens,lensIndex)==null)throw new AssertionError("Legacy region ID lost its stable catalog alias");
            lens.addProperty("regionId","p1-image-999");
            if(SlideLens.resolve(lens,lensIndex)!=null)throw new AssertionError("Unknown region accepted");
            JsonObject semantic=lensIndex.getAsJsonArray("pages").get(0).getAsJsonObject().getAsJsonArray("slideLensRegions").get(0).getAsJsonObject();
            semantic.addProperty("origin","page-vision-v1");semantic.addProperty("lensReason","none");
            semantic.addProperty("paddingApplied",true);semantic.addProperty("locationState","padded");
            lens.addProperty("regionId","sl1-p1-image-a1b2c3d4e5f6");
            if(SlideLens.resolve(lens,lensIndex)!=null)throw new AssertionError("Tracking ID forced an unnecessary lens");
            semantic.addProperty("lensReason","layout");
            request=SlideLens.resolve(lens,lensIndex);
            if(request==null || !request.paddingApplied())throw new AssertionError("Semantic padding metadata lost");
            BufferedImage whole=pdf.render(1,2);
            crop=SlideLens.crop(pdf,request);
            if(crop.getWidth()!=(int)Math.ceil(.8*whole.getWidth())-(int)Math.floor(.1*whole.getWidth()))
                throw new AssertionError("Semantic crop padding applied twice");
        }
        try (PdfSource cached=PdfSource.open(ROOT.resolve("text.pdf"),ROOT.resolve("viewer-cache"))) {
            var stored=PdfLibraryStore.list(ROOT.resolve("viewer-cache")).stream()
                .filter(item->item.id().equals(cached.id)).findFirst().orElseThrow();
            if (!stored.name().equals("text.pdf") || !stored.source().equals(cached.folder.resolve("source.pdf")))
                throw new AssertionError("The PDF library did not retain its original name and local copy");
            try (PdfSource reopened=PdfSource.open(stored.source(),ROOT.resolve("viewer-cache"))) {
                if (!reopened.id.equals(cached.id) || !reopened.name.equals("text.pdf"))
                    throw new AssertionError("Opening a library card lost the cached document identity");
            }
        }
        Path deleteRoot=Files.createTempDirectory(ROOT,"delete-cache-");
        String deleteId;
        try (PdfSource stored=PdfSource.open(ROOT.resolve("text.pdf"),deleteRoot)) {
            deleteId=stored.id;
            Path generated=stored.folder.resolve("generated");
            Files.createDirectories(generated);
            Files.writeString(generated.resolve("latest-document-0.json"),"generated summary");
            PdfLibraryStore.deleteGeneratedData(deleteRoot,deleteId);
            if(Files.exists(generated) || !Files.isRegularFile(stored.folder.resolve("source.pdf"))
                    || PdfLibraryStore.list(deleteRoot).stream().noneMatch(item->item.id().equals(deleteId)))
                throw new AssertionError("Data deletion must preserve the stored PDF and library entry");
        }
        SwingUtilities.invokeAndWait(()->{
            PdfLibraryPanel library=new PdfLibraryPanel(deleteRoot,path->{});
            try {
                var cardMethod=PdfLibraryPanel.class.getDeclaredMethod("documentCard",PdfLibraryStore.Item.class);
                cardMethod.setAccessible(true);
                JPanel card=(JPanel)cardMethod.invoke(library,PdfLibraryStore.list(deleteRoot).get(0));
                JButton menu=findChild(card,JButton.class);
                if(menu==null || !"⋮".equals(menu.getText()))
                    throw new AssertionError("Every PDF card needs its own three-dot menu");
                JPopupMenu actions=menu.getComponentPopupMenu();
                if(actions==null || !"이름 바꾸기".equals(((JMenuItem)actions.getComponent(0)).getText())
                        || !"파일 삭제".equals(((JMenuItem)actions.getComponent(2)).getText())
                        || !"데이터 삭제".equals(((JMenuItem)actions.getComponent(3)).getText())
                        || !"파일 탐색기에서 보기".equals(((JMenuItem)actions.getComponent(5)).getText())
                        || !"정보보기".equals(((JMenuItem)actions.getComponent(6)).getText()))
                    throw new AssertionError("PDF card menu actions");
                var itemsField=PdfLibraryPanel.class.getDeclaredField("items");
                itemsField.setAccessible(true);
                itemsField.set(library,PdfLibraryStore.list(deleteRoot));
                ((JButton)field(library,"selectionToggle")).doClick();
                if(!((JPanel)field(library,"bulkBar")).isVisible())
                    throw new AssertionError("Bulk selection controls must appear");
                JPanel selectable=(JPanel)cardMethod.invoke(library,PdfLibraryStore.list(deleteRoot).get(0));
                JLabel selectableCover=(JLabel)((Map<?,?>)field(library,"covers")).get(deleteId);
                var selectionClick=new java.awt.event.MouseEvent(selectableCover,
                    java.awt.event.MouseEvent.MOUSE_CLICKED,System.currentTimeMillis(),0,20,20,1,false,
                    java.awt.event.MouseEvent.BUTTON1);
                for(var listener:selectableCover.getMouseListeners())listener.mouseClicked(selectionClick);
                if(!((JButton)field(library,"deleteSelectedFiles")).isEnabled()
                        || !((JButton)field(library,"deleteSelectedData")).isEnabled()
                        || !((JLabel)field(library,"selectedCount")).getText().equals("1개 선택"))
                    throw new AssertionError("Selecting a card must enable both bulk delete actions: "
                        +((JLabel)field(library,"selectedCount")).getText()+", "
                        +((JButton)field(library,"deleteSelectedFiles")).isEnabled());
                ((JButton)field(library,"clearSelection")).doClick();
                if(((JButton)field(library,"deleteSelectedFiles")).isEnabled())
                    throw new AssertionError("Clearing selection must disable bulk delete");
                ((JButton)field(library,"selectAll")).doClick();
                if(!((JLabel)field(library,"selectedCount")).getText().equals(
                        ((List<?>)field(library,"items")).size()+"개 선택"))
                    throw new AssertionError("Select all must select visible documents: "
                        +((JLabel)field(library,"selectedCount")).getText()+", items="
                        +((List<?>)field(library,"items")).size());
                DropTarget libraryDrop=selectableCover.getDropTarget();
                FileHover hover=new FileHover(libraryDrop,true);
                libraryDrop.dragEnter(hover);
                if(!hover.accepted || !(boolean)field(field(library,"dropOverlay"),"active"))
                    throw new AssertionError("Library PDF drag must activate the full-screen overlay");
                library.setSize(900,600);layout(library);
                snapshot(library,"library-drop-overlay.png");
                FileHover unsupported=new FileHover(libraryDrop,false);
                libraryDrop.dragOver(unsupported);
                if(!unsupported.rejected || (boolean)field(field(library,"dropOverlay"),"active"))
                    throw new AssertionError("Library overlay must hide for non-file drags");
                libraryDrop.dragEnter(new FileHover(libraryDrop,true));
                FileDrop dropped=new FileDrop(libraryDrop,List.of(ROOT.resolve("text.pdf").toFile()),true);
                libraryDrop.drop(dropped);
                if(!Boolean.TRUE.equals(dropped.completed) || (boolean)field(field(library,"dropOverlay"),"active"))
                    throw new AssertionError("Library PDF drop must import and dismiss its overlay");
            } catch(Exception failure) {throw new AssertionError("PDF library card menu",failure);}
            finally {library.close();}
        });
        PdfLibraryStore.deleteFile(deleteRoot,deleteId);
        if(!PdfLibraryStore.list(deleteRoot).isEmpty() || !Files.isRegularFile(ROOT.resolve("text.pdf")))
            throw new AssertionError("File deletion must remove only the stored copy and its data");
        Files.delete(deleteRoot);
        if(!PdfWorkspace.acceptsFiles(List.of(ROOT.resolve("text.pdf").toFile())))throw new AssertionError("PDF drop");
        if(PdfWorkspace.acceptsFiles(List.of(ROOT.resolve("scan.png").toFile())))throw new AssertionError("Image drop");
        if(PdfWorkspace.acceptsFiles(List.of(ROOT.resolve("text.pdf").toFile(),ROOT.resolve("scan.pdf").toFile())))throw new AssertionError("Multiple drop");
        if(!PdfWorkspace.acceptsPdfFiles(List.of(ROOT.resolve("text.pdf").toFile(),ROOT.resolve("scan.pdf").toFile())))
            throw new AssertionError("Multiple PDF drop should be accepted");
        JsonObject generatedCost=new JsonObject();generatedCost.addProperty("model","gpt-6-luna");
        JsonObject generationUsage=new JsonObject();generationUsage.addProperty("requests",2);
        generationUsage.addProperty("inputTokens",12000);generationUsage.addProperty("outputTokens",4000);
        generationUsage.addProperty("usageBasedUsd",.0032);generationUsage.addProperty("unknownUsageRequests",0);
        JsonObject byKind=new JsonObject(),visionUsage=new JsonObject();
        visionUsage.addProperty("requests",1);visionUsage.addProperty("usageBasedUsd",.0012);
        byKind.add("page_visual",visionUsage);generationUsage.add("byKind",byKind);
        generationUsage.addProperty("uncertainReservedUsd",0);generatedCost.add("runUsage",generationUsage);
        String generationReport=PdfWorkspace.generationRunReportHtml(generatedCost);
        if(!generationReport.contains("$0.003200") || !generationReport.contains("크레딧")
            || generationReport.contains("새 API 요청") || generationReport.contains("페이지 이미지 분석:"))
            throw new AssertionError("Generation cost report");
        JsonObject approvedRequest=new JsonObject();approvedRequest.addProperty("approvedEstimateUsd",.0016);
        String compared=PdfWorkspace.generationRunReportHtml(generatedCost,approvedRequest);
        if(!compared.contains("예상 비용: $0.001600") ||
           !compared.contains("$0.003200") ||
           !compared.contains("+0.001600 USD · +2.24원 (+100.0%)"))
            throw new AssertionError("Approved estimate and measured usage comparison");
        JsonObject semanticPlan=new JsonObject();semanticPlan.addProperty("strategy","semantic-v1");
        semanticPlan.addProperty("total",2);semanticPlan.addProperty("cached",0);
        semanticPlan.addProperty("partial",0);semanticPlan.addProperty("pending",2);
        semanticPlan.addProperty("costEstimateUsd",.01);
        semanticPlan.addProperty("additionalCostEstimateUsd",.008);
        semanticPlan.addProperty("totalCostEstimateUsd",.0189);
        if(!PdfWorkspace.pagePlanHtml(semanticPlan).contains("전체 생성 예상 비용: 약 $0.0189") ||
           !PdfWorkspace.pagePlanHtml(semanticPlan).contains("기본 예상치 × 1.05"))
            throw new AssertionError("Semantic plan should include every paid generation stage");
        generationUsage.addProperty("requests",0);generationUsage.addProperty("usageBasedUsd",0);
        if(!PdfWorkspace.generationRunReportHtml(generatedCost).contains("새 비용이 들지 않았어요"))
            throw new AssertionError("Cached generation cost report");
        try {PdfSource invalid=PdfSource.open(ROOT.resolve("invalid.pdf"),ROOT.resolve("viewer-cache"));invalid.close();throw new AssertionError("Invalid PDF accepted");}catch(java.io.IOException expected){}
        AtomicReference<PdfWorkspace> panel=new AtomicReference<>();
        java.util.List<PdfWorkspace.PdfLocation> locations=new java.util.ArrayList<>();
        java.util.List<PdfWorkspace.PdfLocation> openings=new java.util.concurrent.CopyOnWriteArrayList<>();
        SwingUtilities.invokeAndWait(()->{PdfWorkspace p=new PdfWorkspace(false,ROOT.resolve("viewer-cache"));panel.set(p);p.addPropertyChangeListener(PdfWorkspace.PDF_LOCATION_PROPERTY,
            event->locations.add((PdfWorkspace.PdfLocation)event.getNewValue()));
            p.addPropertyChangeListener(PdfWorkspace.PDF_OPENED_PROPERTY,
                event->openings.add((PdfWorkspace.PdfLocation)event.getNewValue()));
            p.setSize(1240,760);layout(p);checkDrop(p);});
        try {
            long deadline=System.currentTimeMillis()+120_000; boolean[] ready={false};
            while(System.currentTimeMillis()<deadline){SwingUtilities.invokeAndWait(()->ready[0]=panel.get().ready());if(ready[0])break;Thread.sleep(100);}
            if(!ready[0])throw new AssertionError("Local extraction timed out");
            testStrategyIsolation(panel.get());
            testLiveSummaryPreview(panel.get());
            if(PdfWorkspace.generationPercent("의미 단위 · 원문 판독",1,2)!=18 ||
               PdfWorkspace.generationPercent("의미 단위 · 앞뒤 연결과 예시 과정 판단",2,2)!=50 ||
               PdfWorkspace.generationPercent("의미 단위 · 요약과 개념 정리",2,2)!=92 ||
               PdfWorkspace.generationPercent("의미 단위 · 학습 흐름에 맞춰 요약 정리",1,1)!=96)
                throw new AssertionError("Summary progress should span all semantic stages");
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace p=panel.get();
                for(String name:List.of("summaryFontSize","conceptFontSize","tutorFontSize")) {
                    JSlider slider=(JSlider)field(p,name);
                    if(slider.getValue()!=16 || slider.getMinimum()!=6 || slider.getMaximum()!=64)
                        throw new AssertionError("Study font size should start at 16pt within 6–64pt");
                }
                if(countFontSizeEntries(p)!=3)
                    throw new AssertionError("All three study panels need direct font-size entry");
                if(PdfWorkspace.parseFontSizeInput(" 16 ",6,64)!=16 ||
                   PdfWorkspace.parseFontSizeInput("6",6,64)!=6 ||
                   PdfWorkspace.parseFontSizeInput("64",6,64)!=64)
                    throw new AssertionError("Valid direct font sizes should be accepted");
                for(String invalid:List.of("5","65","-1","999999999999999999999","16.5","abc")) {
                    try {
                        PdfWorkspace.parseFontSizeInput(invalid,6,64);
                        throw new AssertionError("Invalid direct font size was accepted: "+invalid);
                    } catch(IllegalArgumentException expected) {
                        if(!expected.getMessage().contains("6") || !expected.getMessage().contains("64"))
                            throw new AssertionError("Font size warning omitted the allowed range");
                    }
                }
            });
            if(args.length>0 && args[0].equals("--semantic")){SwingUtilities.invokeAndWait(()->panel.get().close());System.out.println("PdfSemanticUiTest OK");System.exit(0);}
            int[] lensViewportY={0};
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace p=panel.get();
                PdfWorkspace.PdfLocation opening=p.currentPdfLocation();
                if(opening==null || opening.page()!=1 || opening.pageCount()!=3 ||
                    locations.isEmpty() || !opening.equals(locations.get(0)))throw new AssertionError("PDF opening location event");
                JsonObject document=(JsonObject)field(p,"index");
                if(document.get("slideLensRegionCatalogVersion").getAsInt()!=1 ||
                    document.getAsJsonArray("pages").get(0).getAsJsonObject()
                        .getAsJsonArray("slideLensRegions").isEmpty())
                    throw new AssertionError("Prepared source did not persist SlideLens region IDs");
                JSlider summarySize=(JSlider)field(p,"summaryFontSize");
                JSlider conceptSize=(JSlider)field(p,"conceptFontSize");
                JSlider tutorSize=(JSlider)field(p,"tutorFontSize");
                summarySize.setValue(64);
                if(!((JEditorPane)field(p,"summary")).getText().contains("font-size: 64pt"))
                    throw new AssertionError("Summary maximum font size");
                summarySize.setValue(16);
                conceptSize.setValue(6);
                JPanel conceptList=(JPanel)field(p,"conceptList");
                if(!(conceptList.getComponent(0) instanceof JEditorPane conceptInfo)
                    || !conceptInfo.getText().contains("font-size: 6pt"))
                    throw new AssertionError("Concept minimum font size");
                conceptSize.setValue(16);
                tutorSize.setValue(64);
                if(!((JLabel)field(p,"tutorFontValue")).getText().contains("64pt"))
                    throw new AssertionError("Tutor font resize keeps its configured size");
                tutorSize.setValue(16);
                try {
                    JButton visual=(JButton)field(p,"visual");
                    if(!visual.isEnabled() || !visual.getText().contains("페이지 전체 분석")) throw new AssertionError("Selected image control");
                    PdfSource fixture=(PdfSource)field(p,"source");
                    Path visualFile=fixture.folder.resolve("generated/visual-pages/page-00001.json");
                    Files.createDirectories(visualFile.getParent());
                    JsonObject visualResult=JsonParser.parseString("""
                        {"kind":"visual_interpretation","page":1,"description":"받침점 양쪽의 힘",
                         "visibleRelationships":["방향을 비교한다"],"uncertainDetails":["화살표 길이는 불명확하다"]}
                        """).getAsJsonObject();
                    visualResult.addProperty("documentId",fixture.id);
                    visualResult.addProperty("sourceFingerprint",document.get("fingerprint").getAsString());
                    Files.writeString(visualFile,visualResult.toString());
                    p.showPage(1);
                    JEditorPane original=(JEditorPane)field(p,"original");
                    if(!original.getDocument().getText(0,original.getDocument().getLength()).contains("받침점 양쪽의 힘"))
                        throw new AssertionError("Separate page visual interpretation");
                    if(!visual.getText().contains("페이지 전체 분석")) throw new AssertionError("Selected image button remains available");
                    Files.deleteIfExists(visualFile);
                    p.showPage(1);
                } catch(Exception error) {throw new RuntimeException(error);}
                JsonObject firstPage=document.getAsJsonArray("pages").get(0).getAsJsonObject();
                JsonElement originalMarkdown=firstPage.get("markdown");
                firstPage.addProperty("markdown","페이지 전체 미리보기 시작 "+"내용 ".repeat(80)+"페이지 끝 확인");
                try {
                    var render=PdfWorkspace.class.getDeclaredMethod("renderSummary");render.setAccessible(true);render.invoke(p);
                    JEditorPane preview=(JEditorPane)field(p,"summary");
                    String visibleText=preview.getDocument().getText(0,preview.getDocument().getLength());
                    if(!visibleText.replaceAll("\\s+", " ").contains("페이지 끝 확인"))throw new AssertionError("Full-page preview was truncated");
                    JSlider size=(JSlider)field(p,"summaryFontSize");size.setValue(18);
                    if(!preview.getText().contains("font-size: 18pt"))throw new AssertionError("Summary font size slider");
                    size.setValue(15);
                    if(!UiFonts.FAMILY.equals(p.getFont().getFamily()))throw new AssertionError("PDF UI typeface");
                } catch(Exception error) {throw new RuntimeException(error);}
                finally {firstPage.add("markdown",originalMarkdown);}
                try {
                    QuizPanel quiz=(QuizPanel)field(p,"quiz");
                    if(!quiz.settings.isEnabled())throw new AssertionError("Quiz settings readiness");
                    QuizPanel.Settings form=new QuizPanel.Settings(3,1,3,"최상","코드 문제 위주");
                    if(!form.level.getSelectedItem().equals("최상") || !form.extra.getText().equals("코드 문제 위주"))throw new AssertionError("Quiz settings");
                    if(((SpinnerNumberModel)form.to.getModel()).getMaximum().equals(3) == false)throw new AssertionError("Quiz page limit");
                    var show=PdfWorkspace.class.getDeclaredMethod("showTab",String.class);show.setAccessible(true);show.invoke(p,"퀴즈로 학습하기");
                    layout(p);snapshot(p,"quiz-scaffold.png");
                    form.setSize(480,320);layout(form);snapshot(form,"quiz-settings.png");
                    show.invoke(p,"요약");
                } catch(Exception error){throw new RuntimeException(error);}
                JComboBox<?> range=(JComboBox<?>)field(p,"scope");
                range.setSelectedIndex(1);
                range.setSelectedIndex(0);
                JScrollPane continuous=(JScrollPane)field(p,"imageScroll");
                p.showPage(1);
                int beforeWheel=continuous.getVerticalScrollBar().getValue();
                if(continuous.getVerticalScrollBar().getUnitIncrement()!=6)
                    throw new AssertionError("PDF wheel increment must be 25% of the former 24-pixel step");
                for(int notch=0;notch<4;notch++)continuous.dispatchEvent(new java.awt.event.MouseWheelEvent(continuous,
                    java.awt.event.MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),0,60,60,0,false,
                    java.awt.event.MouseWheelEvent.WHEEL_UNIT_SCROLL,20,3));
                if(continuous.getVerticalScrollBar().getValue()<=beforeWheel || p.currentPage()<2)
                    throw new AssertionError("Immediate mouse wheel page scrolling");
                JButton thumbnails=(JButton)field(p,"thumbnailToggle");thumbnails.doClick();layout(p);
                JScrollPane thumbView=(JScrollPane)field(p,"thumbnailScroll");
                if(!thumbView.isVisible())throw new AssertionError("Thumbnail index opens");
                JPanel thumbCanvas=(JPanel)field(p,"thumbnailCanvas");
                thumbCanvas.dispatchEvent(new java.awt.event.MouseEvent(thumbCanvas,
                    java.awt.event.MouseEvent.MOUSE_CLICKED,System.currentTimeMillis(),0,70,198+30,1,false));
                if(p.currentPage()!=2)throw new AssertionError("Thumbnail page selection");
                p.showPage(3);if(p.currentPage()!=3)throw new AssertionError("Page navigation");
                if(!p.currentPdfLocation().documentId().equals(opening.documentId()) ||
                    !locations.get(locations.size()-1).equals(p.currentPdfLocation()))throw new AssertionError("PDF page location event");
                JTextField search=(JTextField)field(p,"search");search.setText("회전운동");search.postActionEvent();
                JList<?> hits=(JList<?>)field(p,"searchResults");if(hits.getModel().getSize()!=1)throw new AssertionError("Literal search");hits.setSelectedIndex(0);
                if(p.currentPage()!=2)throw new AssertionError("Search result navigation");
                JEditorPane summary=(JEditorPane)field(p,"summary");
                var click=new javax.swing.event.HyperlinkEvent(summary,javax.swing.event.HyperlinkEvent.EventType.ACTIVATED,null,"page:3");
                for(var listener:summary.getHyperlinkListeners())listener.hyperlinkUpdate(click);
                if(p.currentPage()!=3)throw new AssertionError("Citation click navigation");
            });
            checkPdfZoom(panel.get());
            checkPdfReflow(panel.get());
            checkLocalGreeting(panel.get());
            checkTutorMemory(panel.get());
            Thread.sleep(1000);
            SwingUtilities.invokeAndWait(()->{
                try {PdfWorkspace p=panel.get();layout(p);snapshot(p,"workspace.png");p.previewOverlay(true);snapshot(p,"drop-overlay.png");p.previewOverlay(false);}
                catch(Exception failure){throw new RuntimeException(failure);}
            });
            SwingUtilities.invokeAndWait(()->{
                try {
                    PdfWorkspace p=panel.get();
                    JsonObject result=JsonParser.parseString("""
                      {"model":"UI fixture - NOT a model response","scope":"document","page":0,
                       "overview":{"title":"화면 검증용 요약","body":"테스트용 고정 문구입니다.","easyExplanation":"쉽게 말하면 에너지는 형태를 바꾸며 이동해요.","evidence":[{"page":1}]},"sections":[],
                       "concepts":[{"name":"에너지 보존","pages":[1,3],"entries":[{"definition":"외부와 에너지를 교환하지 않는 계에서 총에너지는 일정합니다.","explanation":"마찰이 작용하면 역학적 에너지 일부가 열에너지로 바뀝니다.","easyExplanation":"쉽게 말하면 에너지가 사라진 게 아니라 열로 바뀐 거예요.","example":"","confusion":"총에너지와 역학적 에너지를 구분합니다.","evidence":[{"page":1},{"page":3}]}]},
                       {"name":"일과 힘","pages":[2],"entries":[{"definition":"일은 힘과 이동 방향의 관계로 정의한다.","explanation":"","example":"","confusion":"","evidence":[{"page":2}]}]}]}
                      """).getAsJsonObject();
                    result.getAsJsonObject("overview").addProperty("body",
                        "## 핵심 관계\n\n1. **에너지 보존**을 확인합니다.\n2. 식 $E=mc^2$를 읽습니다.\n\n"
                        + "| 개념 | 확인할 점 |\n| --- | --- |\n| 에너지 | 형태 변화 |");
                    result.add("pageAnalysisIncompletePages",JsonParser.parseString("[2]").getAsJsonArray());
                    result.add("incompleteStudyPages",JsonParser.parseString("[3]").getAsJsonArray());
                    result.addProperty("standardKnowledgeUsed",true);
                    var f=PdfWorkspace.class.getDeclaredField("generated");f.setAccessible(true);f.set(p,result);
                    var render=PdfWorkspace.class.getDeclaredMethod("renderSummary");render.setAccessible(true);render.invoke(p);
                    JEditorPane summary=(JEditorPane)field(p,"summary");
                    if(!summary.getText().contains("<table") || !summary.getText().contains("synesis-study-math"))
                        throw new AssertionError("Summary Markdown table/math rendering");
                    String reading=summary.getDocument().getText(0,summary.getDocument().getLength());
                    if(reading.contains("페이지 이미지 분석 결과 없음") || reading.contains("학습 내용 반영 여부")
                        || reading.contains("PDF 직접 추출") || reading.contains("표준 전공 개념 보충"))
                        throw new AssertionError("Technical diagnostics leaked into the study summary");
                    if(!reading.contains("쉬운 설명 보기"))throw new AssertionError("Summary easy explanation toggle");
                    var easyClick=new javax.swing.event.HyperlinkEvent(summary,javax.swing.event.HyperlinkEvent.EventType.ACTIVATED,null,"easy:"+studyKey(p)+"/overview");
                    for(var listener:summary.getHyperlinkListeners())listener.hyperlinkUpdate(easyClick);
                    if(!summary.getDocument().getText(0,summary.getDocument().getLength()).contains("형태를 바꾸며 이동해요"))throw new AssertionError("Summary easy explanation expanded");
                    layout(p);snapshot(p,"summary-easy-expanded.png");
                    for(var listener:summary.getHyperlinkListeners())listener.hyperlinkUpdate(easyClick);
                    if(summary.getDocument().getText(0,summary.getDocument().getLength()).contains("형태를 바꾸며 이동해요"))throw new AssertionError("Summary easy explanation collapsed");
                    JsonObject distinct=result.deepCopy();
                    com.google.gson.JsonArray conceptParts=new com.google.gson.JsonArray();
                    for(String name:new String[]{"상상하기","적용하기"}) {
                        JsonObject part=new JsonObject();part.addProperty("title",name);part.addProperty("body",name+"의 설명입니다.");
                        part.addProperty("easyExplanation",name+"만 쉽게 풀어 설명해요.");
                        part.add("evidence",new com.google.gson.JsonArray());conceptParts.add(part);
                    }
                    distinct.getAsJsonObject("overview").add("parts",conceptParts);
                    f.set(p,distinct);render.invoke(p);
                    String headings=summary.getDocument().getText(0,summary.getDocument().getLength());
                    if(!headings.contains("1. 상상하기") || !headings.contains("2. 적용하기"))throw new AssertionError("Distinct summary part headings");
                    if(headings.split("쉬운 설명 보기",-1).length-1!=2)throw new AssertionError("One easy toggle per concept, without aggregate duplicate");
                    if(headings.indexOf("쉬운 설명 보기")>headings.indexOf("2. 적용하기"))throw new AssertionError("Easy explanation must precede next concept");
                    var partClick=new javax.swing.event.HyperlinkEvent(summary,javax.swing.event.HyperlinkEvent.EventType.ACTIVATED,null,"easy:"+studyKey(p)+"/overview/part-0");
                    for(var listener:summary.getHyperlinkListeners())listener.hyperlinkUpdate(partClick);
                    String partExpanded=summary.getDocument().getText(0,summary.getDocument().getLength());
                    if(!partExpanded.contains("상상하기만 쉽게") || partExpanded.contains("적용하기만 쉽게"))throw new AssertionError("Part easy explanations expand independently");
                    layout(p);snapshot(p,"summary-per-concept-easy.png");
                    for(var listener:summary.getHyperlinkListeners())listener.hyperlinkUpdate(partClick);
                    JsonObject singlePart=result.deepCopy();
                    com.google.gson.JsonArray onePart=new com.google.gson.JsonArray();
                    onePart.add(conceptParts.get(0).deepCopy());
                    singlePart.getAsJsonObject("overview").add("parts",onePart);
                    f.set(p,singlePart);render.invoke(p);
                    String singleHeading=summary.getDocument().getText(0,summary.getDocument().getLength());
                    if(!singleHeading.contains("상상하기") || singleHeading.contains("1. 상상하기"))
                        throw new AssertionError("Single summary part must not be numbered");
                    JsonObject withSections=distinct.deepCopy();
                    withSections.add("sections",JsonParser.parseString("""
                        [{"title":"함수의 역할","body":"함수를 나누어 다시 사용합니다.","easyExplanation":"필요할 때 불러 쓰는 코드예요.","evidence":[]},
                         {"title":"함수의 호출","body":"함수를 호출해 실행합니다.","easyExplanation":"이름을 불러 코드를 실행해요.","evidence":[]}]
                        """).getAsJsonArray());
                    f.set(p,withSections);render.invoke(p);
                    String sectionText=summary.getDocument().getText(0,summary.getDocument().getLength());
                    if(!sectionText.contains("함수의 역할") || !sectionText.contains("함수를 나누어 다시 사용합니다.")
                        || !sectionText.contains("함수의 호출") || !sectionText.contains("쉬운 설명 보기")
                        || sectionText.contains("필요할 때 불러 쓰는 코드예요.")
                        || summary.getText().contains("section-toggle:"))
                        throw new AssertionError("Summary sections should be visible, with only easy explanation toggles");
                    var sectionNavigate=PdfWorkspace.class.getDeclaredMethod("navigate",String.class);sectionNavigate.setAccessible(true);
                    sectionNavigate.invoke(p,"easy:"+studyKey(p)+"/section-0");
                    sectionText=summary.getDocument().getText(0,summary.getDocument().getLength());
                    if(!sectionText.contains("필요할 때 불러 쓰는 코드예요.")
                        || sectionText.contains("이름을 불러 코드를 실행해요."))
                        throw new AssertionError("Section easy explanation should expand independently");
                    f.set(p,result);
                    var method=PdfWorkspace.class.getDeclaredMethod("showConcepts");method.setAccessible(true);method.invoke(p);
                    ((JToggleButton)((java.util.Map<?,?>)field(p,"tabButtons")).get("개념정리")).doClick();
                    ((JLabel)field(p,"status")).setText("화면 검증용 고정 데이터 · 실제 AI 응답 아님");
                    JPanel list=(JPanel)field(p,"conceptList");JPanel first=(JPanel)list.getComponent(0);((JButton)((JPanel)first.getComponent(0)).getComponent(0)).doClick();
                    layout(p);layout(p);snapshot(p,"concepts-ui-fixture.png");
                    if(first.getHeight()<150 || first.getHeight()>600)throw new AssertionError("Concept accordion layout");
                    JPanel content=(JPanel)first.getComponent(1);JPanel easyPanel=(JPanel)content.getComponent(1);
                    JButton easyButton=(JButton)easyPanel.getComponent(0);JEditorPane easyDetails=(JEditorPane)easyPanel.getComponent(1);
                    if(easyDetails.isVisible())throw new AssertionError("Concept easy explanation should start closed");
                    easyButton.doClick();if(!easyDetails.isVisible())throw new AssertionError("Concept easy explanation expanded");
                    layout(p);snapshot(p,"concept-easy-expanded.png");
                    easyButton.doClick();if(easyDetails.isVisible())throw new AssertionError("Concept easy explanation collapsed");
                    JsonObject local=result.deepCopy();
                    JsonObject damagedNative=new JsonObject();damagedNative.addProperty("body","낯설게 보기입니다. [OCR 표기 불확실: 자싞]");
                    JsonObject nativeEvidence=new JsonObject();nativeEvidence.addProperty("source","native");
                    com.google.gson.JsonArray nativeCitations=new com.google.gson.JsonArray();nativeCitations.add(nativeEvidence);damagedNative.add("evidence",nativeCitations);
                    var studentText=PdfWorkspace.class.getDeclaredMethod("studentText",JsonObject.class,String.class);studentText.setAccessible(true);
                    if(((String)studentText.invoke(null,damagedNative,"body")).contains("OCR 표기"))throw new AssertionError("Native font mapping mislabeled OCR");
                    nativeEvidence.addProperty("source","ocr");
                    if(!((String)studentText.invoke(null,damagedNative,"body")).contains("OCR 표기"))throw new AssertionError("Real OCR uncertainty removed");
                    local.getAsJsonObject("overview").addProperty("body","기존 전용 요약입니다.");
                    // Reflection loses the generic type; this test controls both the key and value.
                    @SuppressWarnings("unchecked") java.util.Map<String,JsonObject> products =
                        (java.util.Map<String,JsonObject>)field(p,"products");
                    products.put(studyKey(p),local);
                    var select=PdfWorkspace.class.getDeclaredMethod("selectProduct");select.setAccessible(true);select.invoke(p);
                    render.invoke(p);
                    ((JToggleButton)((java.util.Map<?,?>)field(p,"tabButtons")).get("요약")).doClick();
                    String visible=summary.getDocument().getText(0,summary.getDocument().getLength());
                    if(!visible.contains("기존 전용"))throw new AssertionError("Local summary display");
                    layout(p);snapshot(p,"local-summary.png");
                    JScrollPane localSummaryScroll=(JScrollPane)field(p,"summaryScroll");
                    int textWidth=summary.getWidth(),viewWidth=localSummaryScroll.getViewport().getView().getWidth();
                    if(Math.abs(textWidth-viewWidth*.85)>3 || Math.abs(summary.getX()-(viewWidth-textWidth)/2)>2)
                        throw new AssertionError("Summary text should use centered 85% width");
                    JsonObject imageAnswer=new JsonObject();imageAnswer.addProperty("regionId","smoke-region");
                    imageAnswer.addProperty("page",2);imageAnswer.addProperty("description","## 선택한 그림\n\n**화살표**가 오른쪽을 가리킵니다.");
                    imageAnswer.add("uncertainDetails",new JsonArray());
                    var navigate=PdfWorkspace.class.getDeclaredMethod("navigate",String.class);navigate.setAccessible(true);
                    JEditorPane detail=(JEditorPane)field(p,"visualDetail");
                    JsonObject batch=new JsonObject();batch.addProperty("total",4);batch.addProperty("completed",4);
                    batch.addProperty("skipped",3);batch.addProperty("accountedUsd",.001);
                    batch.addProperty("localZeroSkips",2);
                    JsonObject runUsage=new JsonObject();runUsage.addProperty("imageRequests",1);
                    runUsage.addProperty("confirmedImageRequests",1);
                    runUsage.addProperty("imageRegions",1);runUsage.addProperty("textOnlyRequests",1);
                    runUsage.addProperty("usageBasedUsd",.00026);runUsage.addProperty("inputTokens",1100);
                    runUsage.addProperty("outputTokens",300);runUsage.addProperty("unknownUsageRequests",0);
                    runUsage.addProperty("uncertainReservedUsd",0);batch.add("runUsage",runUsage);
                    String costReport=PdfWorkspace.imageAnalysisRunReportHtml(batch);
                    if(!costReport.contains("Luna 응답이 확인된 이미지 전송: <b>1회")
                        || !costReport.contains("$0.000260") || !costReport.contains("추가 호출 없이 제외: 2개"))
                        throw new AssertionError("Image analysis run cost report");
                    imageAnswer.addProperty("regionId","auto-smoke-region");imageAnswer.addProperty("regionIndex",0);
                    imageAnswer.addProperty("importance",2);imageAnswer.addProperty("roleReason","문맥에서 작동 원리를 설명합니다.");
                    JsonArray purposes=new JsonArray();purposes.add("concept_explanation");imageAnswer.add("purposes",purposes);
                    JsonArray explanations=new JsonArray();explanations.add(imageAnswer);batch.add("explanations",explanations);
                    JToggleButton summaryTab=(JToggleButton)((java.util.Map<?,?>)field(p,"tabButtons")).get("요약");summaryTab.doClick();
                    int notices=((List<?>)field(p,"conversation")).size();
                    var display=PdfWorkspace.class.getDeclaredMethod("displayImageAnalysis",JsonObject.class);display.setAccessible(true);
                    display.invoke(p,batch);display.invoke(p,batch);
                    if(((List<?>)field(p,"conversation")).size()!=notices || !summaryTab.isSelected())
                        throw new AssertionError("Background image analysis should not interrupt tutor chat");
                    if(!((JButton)field(p,"analyzeImages")).isEnabled())throw new AssertionError("Image batch action readiness");
                    navigate.invoke(p,"visual:auto-smoke-region");
                    if(!detail.getDocument().getText(0,detail.getDocument().getLength()).contains("화살표"))
                        throw new AssertionError("Automatic image explanation opens");
                    layout(p);snapshot(p,"selected-image-explanation.png");
                    String labeled=detail.getDocument().getText(0,detail.getDocument().getLength());
                    if(!labeled.contains("2 · 핵심 설명") || !labeled.contains("개념 설명") || !labeled.contains("문맥상 추정"))
                        throw new AssertionError("Image importance and purpose labels");
                    JsonArray assessments=new JsonArray();assessments.add(imageAnswer.deepCopy());
                    JsonObject decorative=imageAnswer.deepCopy();decorative.addProperty("importance",0);
                    JsonArray branding=new JsonArray();branding.add("decoration");decorative.add("purposes",branding);
                    decorative.addProperty("roleReason","장식용 마스코트");
                    decorative.addProperty("decisionSource","fixed_repeat_cache");assessments.add(decorative);
                    JsonObject unknown=imageAnswer.deepCopy();unknown.add("importance",JsonNull.INSTANCE);assessments.add(unknown);
                    batch.add("assessments",assessments);
                    display.invoke(p,batch);
                    if(!((JButton)field(p,"imageReport")).isEnabled())throw new AssertionError("Image report readiness");
                    String reportBody=PdfWorkspace.imageAssessmentReportHtml(assessments);
                    if(!reportBody.contains("0 · 설명 생략") || !reportBody.contains("판단 보류") || !reportBody.contains("장식용 마스코트") || !reportBody.contains("추가 호출 없이 제외"))
                        throw new AssertionError("Skipped and uncertain image assessments remain inspectable");
                    JEditorPane report=new JEditorPane("text/html",reportBody);report.setSize(650,430);
                    snapshot(report,"image-importance-report.png");
                    JsonObject prepared=(JsonObject)field(p,"index");
                    JsonObject pageOne=prepared.getAsJsonArray("pages").get(0).getAsJsonObject();
                    pageOne.add("imageRegions",JsonParser.parseString("[{\"bbox\":[0.12,0.18,0.82,0.72]}]").getAsJsonArray());
                    pageOne.add("slideLensRegions",JsonParser.parseString("""
                        [{"regionId":"sl1-p1-image-a1b2c3d4e5f6","legacyId":"p1-image-0",
                          "kind":"image","bbox":[0.12,0.18,0.82,0.72],"sourceIndex":0}]
                        """).getAsJsonArray());
                    JsonObject cropModule=JsonParser.parseString("""
                        {"moduleId":"synesis.slide-lens","schemaVersion":1,"regionId":"sl1-p1-image-a1b2c3d4e5f6",
                         "page":1,"kind":"image","bbox":[0.12,0.18,0.82,0.72]}
                        """).getAsJsonObject();
                    JsonObject withLens=result.deepCopy();
                    JsonObject lensPart=new JsonObject();lensPart.addProperty("title","그림으로 확인");
                    lensPart.addProperty("body",("그림 앞 설명입니다. 강의 교안의 이 부분을 확인합니다.\n\n").repeat(35)
                        +"[[SLIDE_LENS]]\n\n"+("그림 뒤 설명입니다. 원문과 함께 살펴봅니다.\n\n").repeat(35));
                    lensPart.addProperty("easyExplanation","");
                    lensPart.add("evidence",JsonParser.parseString("[{\"page\":1}]").getAsJsonArray());
                    lensPart.add("slideLens",cropModule.deepCopy());
                    lensPart.add("stepFlow",StepFlowTest.fixtureModule());
                    JsonArray lensParts=new JsonArray();lensParts.add(lensPart);
                    withLens.getAsJsonObject("overview").add("parts",lensParts);
                    withLens.getAsJsonArray("concepts").get(0).getAsJsonObject().getAsJsonArray("entries")
                        .get(0).getAsJsonObject().add("slideLens",cropModule.deepCopy());
                    withLens.getAsJsonArray("concepts").get(0).getAsJsonObject().getAsJsonArray("entries")
                        .get(0).getAsJsonObject().addProperty("explanation",
                            "개념 그림 앞 설명입니다.\n\n[[SLIDE_LENS]]\n\n개념 그림 뒤 설명입니다.");
                    withLens.getAsJsonArray("concepts").get(0).getAsJsonObject().getAsJsonArray("entries")
                        .get(0).getAsJsonObject().add("stepFlow",StepFlowTest.fixtureModule());
                    f.set(p,withLens);render.invoke(p);method.invoke(p);summaryTab.doClick();layout(p);
                    JScrollPane summaryScroll=(JScrollPane)field(p,"summaryScroll");
                    if(!summaryScroll.getViewport().getView().getClass().getSimpleName().equals("SummaryFlow")
                        || findChild(summaryScroll.getViewport(),SlideLens.Panel.class)==null)
                        throw new AssertionError("SlideLens did not appear inside summary flow");
                    if(findChild((JPanel)field(p,"conceptList"),SlideLens.Panel.class)==null)
                        throw new AssertionError("SlideLens did not appear inside concept card");
                    assertLensBetweenText((Container)summaryScroll.getViewport().getView(),
                        "그림 앞 설명", "그림 뒤 설명");
                    SlideLens.Panel conceptLens=findChild((JPanel)field(p,"conceptList"),SlideLens.Panel.class);
                    assertLensBetweenText(conceptLens.getParent(),"개념 그림 앞 설명","개념 그림 뒤 설명");
                    StepFlow.Panel sequence=findChild(summaryScroll.getViewport(),StepFlow.Panel.class);
                    if(sequence==null || findChild((JPanel)field(p,"conceptList"),StepFlow.Panel.class)==null)
                        throw new AssertionError("StepFlow missing in summary/concept");
                    sequence.select(1);render.invoke(p);layout(p);
                    if(findChild(summaryScroll.getViewport(),StepFlow.Panel.class).selected()!=1)
                        throw new AssertionError("StepFlow selection lost during rerender");
                    SlideLens.Panel lensPanel=findChild(summaryScroll.getViewport(),SlideLens.Panel.class);
                    JViewport viewport=summaryScroll.getViewport();
                    viewport.setViewPosition(new Point(0,Math.max(0,lensPanel.getY()-40)));
                    if(viewport.getViewPosition().y==0)
                        throw new AssertionError("SlideLens scroll regression must start below the top: lens="
                            +lensPanel.getY()+", content="+summaryScroll.getViewport().getView().getPreferredSize().height
                            +", viewport="+viewport.getHeight());
                    lensViewportY[0]=SwingUtilities.convertPoint(lensPanel,0,0,viewport).y;
                    ((JButton)lensPanel.getComponent(0)).doClick();
                    if(!((java.util.Set<?>)field(p,"expandedSlideLens")).contains(studyKey(p)+"/overview/part-0"))
                        throw new AssertionError("SlideLens expand button did not open");
                }catch(Exception failure){throw new RuntimeException(failure);}
            });
            long lensDeadline=System.currentTimeMillis()+15_000;
            while(System.currentTimeMillis()<lensDeadline) {
                boolean[] loaded={false};
                SwingUtilities.invokeAndWait(()->loaded[0]=!((java.util.Map<?,?>)field(panel.get(),"slideLensImages")).isEmpty());
                if(loaded[0])break;
                Thread.sleep(100);
            }
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace p=panel.get();
                if(((java.util.Map<?,?>)field(p,"slideLensImages")).isEmpty())
                    throw new AssertionError("SlideLens crop did not load");
                JScrollPane scroll=(JScrollPane)field(p,"summaryScroll");
                layout(p);try {snapshot(p,"slide-lens-expanded.png");}catch(Exception error){throw new RuntimeException(error);}
                SlideLens.Panel lensPanel=findChild(scroll.getViewport(),SlideLens.Panel.class);
                if(lensPanel==null || findChild(lensPanel,JComponent.class)==null)
                    throw new AssertionError("Expanded SlideLens disappeared");
                int currentY=SwingUtilities.convertPoint(lensPanel,0,0,scroll.getViewport()).y;
                if(Math.abs(currentY-lensViewportY[0])>2)
                    throw new AssertionError("Expanding SlideLens moved its button in the summary viewport: "
                        +lensViewportY[0]+" -> "+currentY+", panelY="+lensPanel.getY()
                        +", scroll="+scroll.getVerticalScrollBar().getValue()
                        +", view="+scroll.getViewport().getViewPosition().y);
                JComponent canvas=findNamedChild(lensPanel,"ResizeCanvas");
                if(canvas==null)throw new AssertionError("Resizable crop canvas missing");
                int beforeWidth=canvas.getPreferredSize().width;
                long now=System.currentTimeMillis();
                canvas.dispatchEvent(new java.awt.event.MouseEvent(canvas,java.awt.event.MouseEvent.MOUSE_PRESSED,
                    now,0,canvas.getWidth()-4,canvas.getHeight()-4,100,100,1,false,java.awt.event.MouseEvent.BUTTON1));
                canvas.dispatchEvent(new java.awt.event.MouseEvent(canvas,java.awt.event.MouseEvent.MOUSE_DRAGGED,
                    now+1,0,canvas.getWidth()+76,canvas.getHeight()-4,180,100,0,false,java.awt.event.MouseEvent.BUTTON1));
                canvas.dispatchEvent(new java.awt.event.MouseEvent(canvas,java.awt.event.MouseEvent.MOUSE_RELEASED,
                    now+2,0,canvas.getWidth()+76,canvas.getHeight()-4,180,100,1,false,java.awt.event.MouseEvent.BUTTON1));
                if(canvas.getPreferredSize().width<=beforeWidth)
                    throw new AssertionError("Dragging the crop corner did not resize it");
                ((JButton)lensPanel.getComponent(0)).doClick();
                if(!((java.util.Set<?>)field(p,"expandedSlideLens")).isEmpty())
                    throw new AssertionError("SlideLens close button did not close");
            });
            SwingUtilities.invokeAndWait(()->panel.get().openPdf(ROOT.resolve("text.pdf")));
            long reopenDeadline=System.currentTimeMillis()+10_000;
            while(openings.size()<2 && System.currentTimeMillis()<reopenDeadline)Thread.sleep(20);
            if(openings.size()<2 || !panel.get().currentPdfName().equals("text.pdf"))
                throw new AssertionError("Reopening the same PDF did not refresh its title");
            awaitReady(panel.get());
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace p=panel.get();
                PdfSource current=(PdfSource)field(p,"source");
                JsonObject prepared=(JsonObject)field(p,"index");
                JsonObject saved=JsonParser.parseString("""
                    {"kind":"ai_generated","promptVersion":"pdf-grounded-ko-v51","scope":"document",
                     "page":0,"model":"gpt-6-luna","sourcePages":[1,2,3],"incompletePages":[],
                     "pageAnalysisIncompletePages":[],"visualNotePages":[],"skippedStudyPages":[],
                     "overview":{"title":"저장된 요약","body":"이미 만든 결과입니다.","evidence":[]},
                     "sections":[],"concepts":[]}
                    """).getAsJsonObject();
                saved.addProperty("documentId",current.id);
                saved.addProperty("sourceFingerprint",prepared.get("fingerprint").getAsString());
                Path latest=current.folder.resolve("generated/latest-document-0.json");
                try {
                    Files.createDirectories(latest.getParent());
                    Files.writeString(latest,saved.toString());
                    var start=PdfWorkspace.class.getDeclaredMethod("startGeneration",long.class,boolean.class);
                    start.setAccessible(true);start.invoke(p,0L,false);
                }catch(Exception error){throw new AssertionError("Cached generation before cost prompt",error);}
            });
            awaitReady(panel.get());
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace p=panel.get();
                try {
                    if(!((JLabel)field(p,"status")).getText().contains("저장된 요약·개념 불러옴"))
                        throw new AssertionError("Saved generation must load before the cost prompt");
                    PdfSource current=(PdfSource)field(p,"source");
                    Files.deleteIfExists(current.folder.resolve("generated/latest-document-0.json"));
                }catch(Exception error){throw new AssertionError("Cached generation before cost prompt",error);}
            });
            AtomicReference<java.util.concurrent.CompletableFuture<Void>> released=new AtomicReference<>();
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace p=panel.get();
                String id=p.currentPdfLocation().documentId();
                released.set(p.releasePdfIfMatches(id));
                JEditorPane summary=(JEditorPane)field(p,"summary");
                String visible;
                try {visible=summary.getDocument().getText(0,summary.getDocument().getLength());}
                catch(Exception failure) {throw new AssertionError(failure);}
                if(p.currentPdfLocation()!=null || !visible.contains("PDF를 불러와 주세요"))
                    throw new AssertionError("Deleted library item remains open in the workspace: location="
                        +p.currentPdfLocation()+", summary="+visible);
            });
            released.get().join();
        } finally {SwingUtilities.invokeAndWait(()->panel.get().close());}
        System.out.println("PASS: PDF render, drop-event import/extraction, search, citation clicks, tutor follow-up memory/reset, drop filter, invalid PDF, offscreen UI. No paid calls.");
        System.exit(0); // Standalone JavaExec smoke test: Swing's event thread can otherwise keep the JVM alive.
    }

    static void checkLocalGreeting(PdfWorkspace panel)throws Exception {
        var analysisHeld=new java.util.concurrent.CountDownLatch(1);
        var releaseAnalysis=new java.util.concurrent.CountDownLatch(1);
        ((java.util.concurrent.ExecutorService)field(panel,"jobs")).execute(()->{
            analysisHeld.countDown();
            try {releaseAnalysis.await();}catch(InterruptedException interrupted){Thread.currentThread().interrupt();}
        });
        if(!analysisHeld.await(5,java.util.concurrent.TimeUnit.SECONDS))
            throw new AssertionError("Analysis queue did not start");
        try {
            SwingUtilities.invokeAndWait(()->{
                try {
                    var setBusy=PdfWorkspace.class.getDeclaredMethod("setBusy",boolean.class,String.class);
                    setBusy.setAccessible(true);setBusy.invoke(panel,true,"요약 생성 중…");
                }catch(Exception failure){throw new AssertionError(failure);}
                JButton ask=(JButton)field(panel,"ask");
                if(!ask.isEnabled())throw new AssertionError("Tutor must remain available during summary generation");
                ((JTextArea)field(panel,"question")).setText("ㅎㅇ");
                ask.doClick();
            });
        long deadline=System.currentTimeMillis()+15_000;
        boolean[] complete={false};
        while(System.currentTimeMillis()<deadline) {
            SwingUtilities.invokeAndWait(()->{
                @SuppressWarnings("unchecked") Map<String,JsonObject> answers=
                    (Map<String,JsonObject>)field(panel,"tutorAnswers");
                complete[0]=answers.values().stream().anyMatch(answer->"greeting".equals(answer.get("kind").getAsString()));
            });
            if(complete[0])break;
            Thread.sleep(100);
        }
        if(!complete[0])throw new AssertionError("Tutor was queued behind summary generation");
        SwingUtilities.invokeAndWait(()->{
            try {
                var setBusy=PdfWorkspace.class.getDeclaredMethod("setBusy",boolean.class,String.class);
                setBusy.setAccessible(true);setBusy.invoke(panel,false,"원문 준비 완료");
                var showTab=PdfWorkspace.class.getDeclaredMethod("showTab",String.class);
                showTab.setAccessible(true);showTab.invoke(panel,"AI멘토");
                layout(panel);snapshot(panel,"tutor-greeting.png");
                List<JEditorPane> panes=tutorPanes((JPanel)field(panel,"tutorMessages"));
                if(panes.size()!=2 || !panes.get(1).getDocument().getText(0,
                    panes.get(1).getDocument().getLength()).contains("AI멘토예요"))
                    throw new AssertionError("Damon must introduce himself in the bubble");
                ((JButton)field(panel,"newChat")).doClick();
            } catch(Exception error) {throw new AssertionError("Local tutor greeting",error);}
        });
        } finally {
            releaseAnalysis.countDown();
            SwingUtilities.invokeAndWait(()->{
                try {
                    var setBusy=PdfWorkspace.class.getDeclaredMethod("setBusy",boolean.class,String.class);
                    setBusy.setAccessible(true);setBusy.invoke(panel,false,"원문 준비 완료");
                }catch(Exception failure){throw new AssertionError(failure);}
            });
        }
    }

    static void checkPdfZoom(PdfWorkspace panel)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            panel.showPage(2);
            @SuppressWarnings("unchecked") JComboBox<String> zoom=(JComboBox<String>)field(panel,"zoom");
            JScrollPane scroll=(JScrollPane)field(panel,"imageScroll");
            zoom.setSelectedItem("200%");
            ((JButton)field(panel,"zoomIn")).doClick();
            if(!"205%".equals(zoom.getSelectedItem()))throw new AssertionError("PDF zoom-in button must add 5%");
            scroll.dispatchEvent(new java.awt.event.MouseWheelEvent(scroll,
                java.awt.event.MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),
                java.awt.event.InputEvent.CTRL_DOWN_MASK,80,80,0,false,
                java.awt.event.MouseWheelEvent.WHEEL_UNIT_SCROLL,1,-1));
            if(!"206%".equals(zoom.getSelectedItem()))throw new AssertionError("Ctrl+wheel PDF zoom-in must add 1%: "+zoom.getSelectedItem());
            JPanel canvas=(JPanel)field(panel,"imageCanvas");
            canvas.dispatchEvent(new java.awt.event.MouseWheelEvent(canvas,
                java.awt.event.MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),
                java.awt.event.InputEvent.CTRL_DOWN_MASK,80,80,0,false,
                java.awt.event.MouseWheelEvent.WHEEL_UNIT_SCROLL,1,1));
            if(!"205%".equals(zoom.getSelectedItem()))throw new AssertionError("Ctrl+wheel over PDF page must subtract 1%");
            ((JButton)field(panel,"zoomOut")).doClick();
            if(!"200%".equals(zoom.getSelectedItem()))throw new AssertionError("PDF zoom-out button must subtract 5%");
            for(int index=0;index<2;index++) {
                canvas.dispatchEvent(new java.awt.event.MouseWheelEvent(canvas,
                    java.awt.event.MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),
                    java.awt.event.InputEvent.CTRL_DOWN_MASK,80,80,80,80,0,false,
                    java.awt.event.MouseWheelEvent.WHEEL_UNIT_SCROLL,1,0,.25));
                if(index==0 && !"200%".equals(zoom.getSelectedItem()))
                    throw new AssertionError("Small trackpad delta must accumulate");
            }
            if(!"199%".equals(zoom.getSelectedItem()))throw new AssertionError("Trackpad PDF zoom must be fine-grained");
            zoom.setSelectedItem("너비 맞춤");
        });
        SwingUtilities.invokeAndWait(()->{});
    }

    static void checkPdfReflow(PdfWorkspace panel)throws Exception {
        double[] before={0}, afterPanel={0}, afterResize={0}, afterClose={0}, fixedBefore={0}, fixedAfter={0};
        SwingUtilities.invokeAndWait(()->{
            try {
                panel.showPage(2);
                JScrollPane scroll=(JScrollPane)field(panel,"imageScroll");
                @SuppressWarnings("unchecked") List<Object> layouts=(List<Object>)field(panel,"pageLayouts");
                var bounds=layouts.get(1).getClass().getDeclaredMethod("bounds");
                bounds.setAccessible(true);
                Rectangle pageBounds=(Rectangle)bounds.invoke(layouts.get(1));
                scroll.getVerticalScrollBar().setValue(pageBounds.y+pageBounds.height/2);
                before[0]=pdfViewportFraction(panel);
                panel.setSidePanelVisible(true);
                layout(panel);
            } catch(Exception error) {throw new RuntimeException(error);}
        });
        Thread.sleep(250);
        SwingUtilities.invokeAndWait(()->{
            try {
                afterPanel[0]=pdfViewportFraction(panel);
                panel.setSize(1050,760);
                layout(panel);
            } catch(Exception error) {throw new RuntimeException(error);}
        });
        Thread.sleep(250);
        SwingUtilities.invokeAndWait(()->{
            try {
                afterResize[0]=pdfViewportFraction(panel);
                if(panel.currentPage()!=2 || Math.abs(before[0]-afterPanel[0])>.12 ||
                    Math.abs(afterPanel[0]-afterResize[0])>.12)
                    throw new AssertionError("PDF reading position changed on side panel or resize: "
                        +before[0]+" -> "+afterPanel[0]+" -> "+afterResize[0]);
                panel.setSidePanelVisible(false);
                panel.setSize(1240,760);
                layout(panel);
            } catch(Exception error) {throw new RuntimeException(error);}
        });
        Thread.sleep(250);
        SwingUtilities.invokeAndWait(()->{
            try {
                afterClose[0]=pdfViewportFraction(panel);
                if(panel.currentPage()!=2 || Math.abs(afterResize[0]-afterClose[0])>.12)
                    throw new AssertionError("Closing the side panel moved the PDF reading position");
                @SuppressWarnings("unchecked") JComboBox<String> zoom=(JComboBox<String>)field(panel,"zoom");
                zoom.setSelectedItem("150%");
            } catch(Exception error) {throw new RuntimeException(error);}
        });
        SwingUtilities.invokeAndWait(()->{});
        SwingUtilities.invokeAndWait(()->{
            try {
                fixedBefore[0]=pdfViewportFraction(panel);
                panel.setSize(1100,700);
                layout(panel);
            } catch(Exception error) {throw new RuntimeException(error);}
        });
        Thread.sleep(250);
        SwingUtilities.invokeAndWait(()->{
            try {
                fixedAfter[0]=pdfViewportFraction(panel);
                if(panel.currentPage()!=2 || Math.abs(fixedBefore[0]-fixedAfter[0])>.12)
                    throw new AssertionError("Fixed-zoom PDF position changed on window resize");
                @SuppressWarnings("unchecked") JComboBox<String> zoom=(JComboBox<String>)field(panel,"zoom");
                zoom.setSelectedItem("너비 맞춤");
                panel.setSize(1240,760);
                layout(panel);
            } catch(Exception error) {throw new RuntimeException(error);}
        });
    }

    static double pdfViewportFraction(PdfWorkspace panel)throws Exception {
        var capture=PdfWorkspace.class.getDeclaredMethod("captureZoomAnchor",Point.class,Point.class);
        capture.setAccessible(true);
        Object anchor=capture.invoke(panel,null,null);
        var fraction=anchor.getClass().getDeclaredMethod("yFraction");
        fraction.setAccessible(true);
        return (double)fraction.invoke(anchor);
    }

    static void checkTutorMemory(PdfWorkspace panel)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            try {
                JPanel body=(JPanel)field(panel,"tutorBody");
                JComboBox<?> mode=(JComboBox<?>)field(panel,"tutorMode");
                JLabel searchHint=(JLabel)field(panel,"tutorSearchHint");
                JButton attach=(JButton)field(panel,"tutorAttach");
                JLabel attachmentLabel=(JLabel)field(panel,"tutorAttachmentLabel");
                if(!body.getComponent(0).isVisible() || !"간단한 설명".equals(mode.getSelectedItem())
                    || mode.getPreferredSize().width<150)
                    throw new AssertionError("Tutor opens with welcome screen and visible mode label");
                mode.setSelectedIndex(1);
                if(!"심층적 설명".equals(mode.getSelectedItem()))throw new AssertionError("Deep mode label");
                mode.setSelectedIndex(0);
                if(!"+".equals(attach.getText()))throw new AssertionError("Tutor attachment button");
                JTextArea question=(JTextArea)field(panel,"question");
                if(!question.getLineWrap() || !question.getWrapStyleWord() || question.getRows()<2)
                    throw new AssertionError("Tutor composer must support multiple wrapped lines");
                InputMap inputKeys=question.getInputMap(JComponent.WHEN_FOCUSED);
                if(!"synesisSendTutor".equals(inputKeys.get(KeyStroke.getKeyStroke(java.awt.event.KeyEvent.VK_ENTER,0)))
                    || !"synesisNewlineTutor".equals(inputKeys.get(KeyStroke.getKeyStroke(
                        java.awt.event.KeyEvent.VK_ENTER,java.awt.event.InputEvent.SHIFT_DOWN_MASK))))
                    throw new AssertionError("Enter must send and Shift+Enter must insert a newline");
                question.setText("첫 줄");question.setCaretPosition(question.getText().length());
                question.getActionMap().get("synesisNewlineTutor").actionPerformed(
                    new java.awt.event.ActionEvent(question,java.awt.event.ActionEvent.ACTION_PERFORMED,"newline"));
                if(!"첫 줄\n".equals(question.getText()))throw new AssertionError("Tutor newline insertion");
                String pasteAction="synesisPasteTutorAttachment";
                if(!pasteAction.equals(question.getInputMap().get(KeyStroke.getKeyStroke("meta V")))
                    || !pasteAction.equals(question.getInputMap().get(KeyStroke.getKeyStroke("control V"))))
                    throw new AssertionError("Tutor image paste shortcuts");
                var paste=PdfWorkspace.class.getDeclaredMethod("pasteTutorTransferable",Transferable.class);
                paste.setAccessible(true);
                BufferedImage clipboardImage=new BufferedImage(32,20,BufferedImage.TYPE_INT_ARGB);
                clipboardImage.setRGB(3,4,Color.BLUE.getRGB());
                Transferable imageTransfer=new Transferable() {
                    public DataFlavor[] getTransferDataFlavors(){return new DataFlavor[]{DataFlavor.imageFlavor};}
                    public boolean isDataFlavorSupported(DataFlavor flavor){return DataFlavor.imageFlavor.equals(flavor);}
                    public Object getTransferData(DataFlavor flavor){return clipboardImage;}
                };
                question.setText("이 그림 설명해줘");
                if(!(boolean)paste.invoke(panel,imageTransfer))throw new AssertionError("Clipboard image paste");
                Path pasted=(Path)field(panel,"tutorAttachment");
                if(pasted==null || !Files.isRegularFile(pasted) || ImageIO.read(pasted.toFile())==null
                    || !question.getText().equals("이 그림 설명해줘") || !attachmentLabel.getText().contains("붙여넣은 이미지"))
                    throw new AssertionError("Pasted image is attached without replacing the question");
                if((boolean)paste.invoke(panel,new StringSelection("텍스트")))
                    throw new AssertionError("Ordinary text must use the normal paste action");
                ((JButton)field(panel,"tutorClearAttachment")).doClick();
                if(Files.exists(pasted))throw new AssertionError("Canceled clipboard image must be removed");
                var setAttachment=PdfWorkspace.class.getDeclaredMethod("setTutorAttachment",Path.class);
                setAttachment.setAccessible(true);
                setAttachment.invoke(panel,ROOT.resolve("scan.png"));
                if(!attachmentLabel.getText().contains("scan.png") || !attachmentLabel.getParent().isVisible())
                    throw new AssertionError("Tutor attachment preview");
                ((JButton)field(panel,"tutorClearAttachment")).doClick();
                if(attachmentLabel.getParent().isVisible())throw new AssertionError("Tutor attachment removal");
                if(!searchHint.getText().contains("외부 검색")
                    || !((FlowLayout)mode.getParent().getLayout()).getAlignOnBaseline())
                    throw new AssertionError("Tutor controls must align and explain optional search");
                var showTab=PdfWorkspace.class.getDeclaredMethod("showTab",String.class);showTab.setAccessible(true);
                showTab.invoke(panel,"AI멘토");layout(panel);snapshot(panel,"tutor-empty.png");
                var greeting=PdfWorkspace.class.getDeclaredMethod("isTutorGreeting",String.class);
                greeting.setAccessible(true);
                if(!(boolean)greeting.invoke(null,"ㅎㅇ") || (boolean)greeting.invoke(null,"안녕, 극좌표를 설명해줘"))
                    throw new AssertionError("Only plain greetings bypass the paid tutor request");
                @SuppressWarnings("unchecked") List<Object> history=(List<Object>)field(panel,"conversation");
                @SuppressWarnings("unchecked") Map<String,JsonObject> answers=(Map<String,JsonObject>)field(panel,"tutorAnswers");
                String marker="SYNESISTUTORANSWERsmoketestEND";
                Class<?> turn=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$TutorTurn");
                var turnConstructor=turn.getDeclaredConstructor(String.class,String.class);
                turnConstructor.setAccessible(true);
                history.add(turnConstructor.newInstance("극좌표가 뭐야?",marker));
                JsonObject result=new JsonObject();result.addProperty("kind","ai_generated");
                result.addProperty("answer","**극좌표**는 \\(r, \\theta\\)로 점을 나타냅니다.");
                result.add("evidence",JsonParser.parseString("[{\"page\":2,\"quote\":\"평면의 한 점을 (r, θ)로 표시\"}]").getAsJsonArray());
                JsonObject tutorUsage=new JsonObject();tutorUsage.addProperty("usageBasedUsd",.0003);
                tutorUsage.addProperty("unknownUsageRequests",0);result.add("runUsage",tutorUsage);
                answers.put(marker,result);
                var render=PdfWorkspace.class.getDeclaredMethod("renderTutor",boolean.class);render.setAccessible(true);
                render.invoke(panel,false);
                JPanel messages=(JPanel)field(panel,"tutorMessages");
                List<JEditorPane> panes=tutorPanes(messages);
                if(panes.size()!=2 || !"RoundedTutorBubble".equals(panes.get(0).getParent().getClass().getSimpleName())
                    || !"RoundedTutorBubble".equals(panes.get(1).getParent().getClass().getSimpleName()))
                    throw new AssertionError("Tutor uses native rounded bubbles");
                String hidden=panes.get(1).getText();
                String visible=panes.get(1).getDocument().getText(0,panes.get(1).getDocument().getLength());
                if(!visible.contains("AI멘토") || !visible.contains("PDF 내 근거 보기")
                    || !visible.contains("이번 답변 최종 비용") || !visible.contains("0.42원")
                    || visible.contains("평면의 한 점을 (r, θ)로 표시")
                    || !hidden.contains("synesis-study-math") || body.getComponent(0).isVisible())
                    throw new AssertionError("Tutor bubbles, math, and collapsed PDF sources");
                layout(panel);snapshot(panel,"tutor-chat.png");
                var navigate=PdfWorkspace.class.getDeclaredMethod("navigate",String.class);navigate.setAccessible(true);
                navigate.invoke(panel,"tutor-evidence:"+marker);
                panes=tutorPanes(messages);
                if(!panes.get(1).getDocument().getText(0,panes.get(1).getDocument().getLength()).contains("평면의 한 점을 (r, θ)로 표시"))
                    throw new AssertionError("Tutor PDF source expands on demand");
                JSlider size=(JSlider)field(panel,"tutorFontSize");size.setValue(64);
                panes=tutorPanes(messages);
                if(!panes.get(1).getText().contains("font-size: 64pt") ||
                    !panes.get(0).getDocument().getText(0,panes.get(0).getDocument().getLength()).contains("극좌표가 뭐야?"))
                    throw new AssertionError("Tutor messages survive font resize");
                size.setValue(18);
                char mathMarker=0x1c;
                result.addProperty("answer","극좌표 "+mathMarker+"(r, \\theta)"+mathMarker
                    +"에서 직각 좌표로 바꿀 때는 "+mathMarker+"(x,y)=(r\\cos\\theta,\\;r\\sin\\theta)"+mathMarker
                    +"를 사용해요. 여기서 "+mathMarker+"r"+mathMarker+"은 거리이고 "
                    +mathMarker+"\\theta"+mathMarker+"는 각이에요.\n\n자료의 삼각형 관계도 "
                    +mathMarker+"x=r\\cos\\theta"+mathMarker+", "
                    +mathMarker+"y=r\\sin\\theta"+mathMarker+"로 나타내요.");
                render.invoke(panel,false);layout(panel);snapshot(panel,"tutor-control-math.png");
            } catch(Exception error) {throw new AssertionError("Tutor UI",error);}
            ((JButton)field(panel,"newChat")).doClick();
            if(!((JsonObject)field(panel,"tutorMemory")).isEmpty() || !((List<?>)field(panel,"conversation")).isEmpty())
                throw new AssertionError("New chat reset");
        });
        SwingUtilities.invokeAndWait(()->panel.openPdf(ROOT.resolve("text.pdf")));
        awaitReady(panel);
        SwingUtilities.invokeAndWait(()->{
            if(!((JsonObject)field(panel,"tutorMemory")).isEmpty() || !((List<?>)field(panel,"conversation")).isEmpty())
                throw new AssertionError("PDF reopen resets tutor");
        });
    }

    static void awaitReady(PdfWorkspace panel)throws Exception {
        long deadline=System.currentTimeMillis()+120_000;
        boolean[] ready={false};
        while(System.currentTimeMillis()<deadline) {
            SwingUtilities.invokeAndWait(()->ready[0]=panel.ready());
            if(ready[0])return;
            Thread.sleep(100);
        }
        throw new AssertionError("Local tutor/PDF task timed out");
    }
    // Mimics a native source that makes file data available only after acceptDrop.
    // This exercises the installed production listener, not openPdf directly.
    static final class FileDrop extends DropTargetDropEvent {
        final Object payload;
        final boolean supported;
        boolean accepted, rejected;
        Boolean completed;
        int reads;
        FileDrop(DropTarget target, Object payload, boolean supported) {
            super(target.getDropTargetContext(), new Point(20,20), DnDConstants.ACTION_COPY,
                    DnDConstants.ACTION_COPY_OR_MOVE, false);
            this.payload=payload; this.supported=supported;
        }
        @Override public boolean isDataFlavorSupported(DataFlavor flavor) {
            return supported && DataFlavor.javaFileListFlavor.equals(flavor);
        }
        @Override public void acceptDrop(int action) {
            if(action!=DnDConstants.ACTION_COPY || accepted || rejected) throw new AssertionError("Invalid acceptance");
            accepted=true;
        }
        @Override public void rejectDrop() {
            if(accepted) throw new AssertionError("Reject after acceptance");
            rejected=true;
        }
        @Override public Transferable getTransferable() {
            return new Transferable() {
                public DataFlavor[] getTransferDataFlavors(){return new DataFlavor[]{DataFlavor.javaFileListFlavor};}
                public boolean isDataFlavorSupported(DataFlavor flavor){return FileDrop.this.isDataFlavorSupported(flavor);}
                public Object getTransferData(DataFlavor flavor) throws java.io.IOException {
                    if(!accepted) throw new InvalidDnDOperationException("Drop not accepted yet");
                    if(completed!=null) throw new AssertionError("Read after completion");
                    reads++;
                    if(payload instanceof java.io.IOException failure) throw failure;
                    return payload;
                }
            };
        }
        @Override public void dropComplete(boolean success) {
            if(!accepted || completed!=null) throw new AssertionError("Invalid completion");
            completed=success;
        }
    }
    static final class FileHover extends DropTargetDragEvent {
        final boolean supported;
        boolean accepted, rejected;
        FileHover(DropTarget target, boolean supported) {
            super(target.getDropTargetContext(), new Point(20,20), DnDConstants.ACTION_COPY,
                    DnDConstants.ACTION_COPY_OR_MOVE);
            this.supported=supported;
        }
        @Override public boolean isDataFlavorSupported(DataFlavor flavor) {
            return supported && DataFlavor.javaFileListFlavor.equals(flavor);
        }
        @Override public Transferable getTransferable() {
            throw new AssertionError("Hover must not read Finder file data before drop");
        }
        @Override public void acceptDrag(int action) {
            if(action!=DnDConstants.ACTION_COPY)throw new AssertionError("Unexpected drag action");
            accepted=true;
        }
        @Override public void rejectDrag() {rejected=true;}
    }
    static void checkDrop(PdfWorkspace panel) {
        DropTarget target=((JLabel)field(panel,"pageImage")).getDropTarget();
        if(panel.getDropTarget()==null || ((JEditorPane)field(panel,"summary")).getDropTarget()==null)
            throw new AssertionError("PDF drop must cover the workspace, including the results pane");
        FileHover hover=new FileHover(target,true);
        target.dragEnter(hover);
        if(!hover.accepted || hover.rejected || !(boolean)field(field(panel,"overlay"),"active"))
            throw new AssertionError("Finder file drag must remain accepted before file data is readable");
        FileHover other=new FileHover(target,false);
        target.dragOver(other);
        if(!other.rejected || (boolean)field(field(panel,"overlay"),"active"))
            throw new AssertionError("Non-file drags must be rejected");
        FileDrop unsupported=new FileDrop(target,List.of(),false);
        target.drop(unsupported);
        if(!unsupported.rejected || unsupported.accepted || unsupported.reads!=0)throw new AssertionError("Unsupported drop");
        FileDrop valid=new FileDrop(target,List.of(ROOT.resolve("text.pdf").toFile()),true);
        panel.previewOverlay(true); target.drop(valid);
        if(!valid.accepted || !Boolean.TRUE.equals(valid.completed) || valid.reads!=1)
            throw new AssertionError("PDF drop must accept before reading and complete once");
        if((boolean)field(field(panel,"overlay"),"active"))throw new AssertionError("Drop overlay left visible");
        FileDrop multiple=new FileDrop(target,List.of(ROOT.resolve("text.pdf").toFile(),ROOT.resolve("scan.pdf").toFile()),true);
        target.drop(multiple);
        if(!Boolean.TRUE.equals(multiple.completed))throw new AssertionError("Multiple PDF drop must complete successfully");
        for(Object payload:List.of(List.of(ROOT.resolve("scan.png").toFile()),
                new java.io.IOException("Synthetic transfer failure"))) {
            FileDrop bad=new FileDrop(target,payload,true); target.drop(bad);
            if(!Boolean.FALSE.equals(bad.completed))throw new AssertionError("Failed drop must complete false after acceptance");
        }
    }
    static Object field(Object object,String name){try{var f=object.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(object);}catch(Exception e){throw new RuntimeException(e);}}
    static int countFontSizeEntries(Container parent) {
        int count=0;
        for(Component child:parent.getComponents()) {
            if(child instanceof JButton button && "글자 크기".equals(button.getText()) &&
                    button.getActionListeners().length>0)count++;
            if(child instanceof Container nested)count+=countFontSizeEntries(nested);
        }
        return count;
    }
    static <T extends Component> T findChild(Container parent,Class<T> type) {
        for(Component child:parent.getComponents()) {
            if(type.isInstance(child))return type.cast(child);
            if(child instanceof Container nested) {
                T found=findChild(nested,type);
                if(found!=null)return found;
            }
        }
        return null;
    }
    static List<JEditorPane> tutorPanes(Container root) {
        List<JEditorPane> panes=new java.util.ArrayList<>();
        for(Component child:root.getComponents()) {
            if(child instanceof JEditorPane pane)panes.add(pane);
            else if(child instanceof Container nested)panes.addAll(tutorPanes(nested));
        }
        return panes;
    }
    static void testStrategyIsolation(PdfWorkspace panel)throws Exception {
        if(!PdfWorkspace.readableStudyVersion(PdfStudyStrategy.VER02_PROMPT)
                || !PdfWorkspace.readableStudyVersion("new-concept-study-ver.02")
                || PdfWorkspace.readableStudyVersion("unrelated-result"))
            throw new AssertionError("ver.02 saved results must survive app restart");
        SwingUtilities.invokeAndWait(()->{
            @SuppressWarnings("unchecked") Map<String,JsonObject> products=(Map<String,JsonObject>)field(panel,"products");
            Map<String,JsonObject> before=new java.util.HashMap<>(products);
            JComboBox<?> selector=(JComboBox<?>)field(panel,"summaryStrategy");int selected=selector.getSelectedIndex();
            if(!studyKey(panel).equals(PdfWorkspace.strategyProductKey("new-concept-v99","document",0)))
                throw new AssertionError("Opening a PDF must default to NewConceptVer, even with legacy caches");
            try {
                JsonObject pageResult=JsonParser.parseString("{\"scope\":\"document\",\"page\":0,\"kind\":\"ai_generated\",\"overview\":{\"title\":\"기존 요약\",\"body\":\"기존 자료예요.\",\"evidence\":[]},\"sections\":[],\"concepts\":[]}").getAsJsonObject();
                JsonObject semantic=pageResult.deepCopy();semantic.addProperty("strategy","semantic-v1");
                semantic.getAsJsonObject("overview").addProperty("title","새 의미 단위 요약");
                products.put(PdfWorkspace.strategyProductKey("page-v1","document",0),pageResult);
                products.put(PdfWorkspace.strategyProductKey("semantic-v1","document",0),semantic);
                selector.setSelectedIndex(1);
                if(field(panel,"generated")!=pageResult)throw new AssertionError("Legacy result lost during strategy switch");
                selector.setSelectedIndex(0);
                if(field(panel,"generated")!=semantic)throw new AssertionError("Semantic result mixed with legacy cache");
                selector.setSelectedIndex(1);
                if(field(panel,"generated")!=pageResult)throw new AssertionError("One-click rollback failed");
                String[] experiments={"region-v1","region-local-v1","slide-v1","new-concept-v1","new-concept-v02","new-concept-v99"};
                for(int i=0;i<experiments.length;i++) {
                    JsonObject region=pageResult.deepCopy();region.addProperty("strategy",experiments[i]);
                    region.add("sections",JsonParser.parseString("""
                        [{"title":"함수","body":"함수는 이름을 붙인 작업 묶음이에요.","easyExplanation":"",
                        "evidence":[{"page":1}],"parts":[{"title":"함수","body":"함수는 이름을 붙인 작업 묶음이에요.",
                        "easyExplanation":"비유: 버튼을 누르면 정해 둔 작업이 실행돼요.","evidence":[{"page":1}]}]}]
                        """));
                    region.add("concepts",JsonParser.parseString("""
                        [{"name":"함수","pages":[1],"entries":[{"definition":"이름을 붙인 작업 묶음이에요.",
                        "explanation":"호출하면 정해 둔 작업을 실행해요.","easyExplanation":"비유: 버튼을 눌러 일을 실행해요.",
                        "example":"","confusion":"","evidence":[{"page":1}]}]}]
                        """));
                    products.put(PdfWorkspace.strategyProductKey(experiments[i],"document",0),region);
                    selector.setSelectedIndex(i+2);
                    if(field(panel,"generated")!=region)throw new AssertionError("Region strategy cache mixed: "+experiments[i]);
                    JPanel summaryFlow=(JPanel)field(panel,"summaryFlow");
                    if(tutorPanes(summaryFlow).stream().noneMatch(p->{
                        try{return p.getDocument().getText(0,p.getDocument().getLength()).contains("함수는 이름을 붙인");}
                        catch(Exception failure){throw new AssertionError(failure);}
                    }))
                        throw new AssertionError("Single-concept region content hidden behind overview");
                    JsonObject plan=new JsonObject();plan.addProperty("strategy",experiments[i]);
                    plan.addProperty("totalPages",3);plan.addProperty("totalCostEstimateUsd",.025);
                    plan.addProperty("estimateBasis","로컬 영역 기준");
                    if(!PdfWorkspace.pagePlanHtml(plan).contains("0.0250"))throw new AssertionError("Region cost plan unavailable");
                    if(i==0)try{layout(panel);snapshot(panel,"region-strategy-single-concept.png");}
                    catch(Exception failure){throw new AssertionError(failure);}
                }
                selector.setSelectedIndex(1);
                try{layout(panel);snapshot(panel,"semantic-strategy-switch.png");}catch(Exception failure){throw new AssertionError(failure);}
            } finally {
                products.clear();products.putAll(before);selector.setSelectedIndex(selected);
                try{var select=PdfWorkspace.class.getDeclaredMethod("selectProduct");select.setAccessible(true);select.invoke(panel);}
                catch(Exception failure){throw new AssertionError(failure);}
            }
        });
    }

    static String studyKey(PdfWorkspace panel) {
        JComboBox<?> strategy=(JComboBox<?>)field(panel,"summaryStrategy");
        return PdfWorkspace.strategyProductKey(new String[]{"semantic-v1","page-v1","region-v1","region-local-v1","slide-v1","new-concept-v1","new-concept-v02","new-concept-v99"}[strategy.getSelectedIndex()],"document",0);
    }

    static void testLiveSummaryPreview(PdfWorkspace panel)throws Exception {
        PdfSource target=(PdfSource)field(panel,"source");
        Path preview=target.folder.resolve("generated/live-preview-test/unit-00001.json");
        Files.createDirectories(preview.getParent());
        JsonObject unit=JsonParser.parseString("""
            {"summary":{"title":"첫 구간","body":"검증을 마친 요약 내용이 완성되자마자 표시됩니다. 첫 번째 부분 다음에 두 번째 부분도 즉시 표시됩니다.",
              "evidence":[{"sourceId":"s1","page":1,"quote":"표본 근거"}],
              "parts":[{"title":"첫 개념","body":"검증을 마친 요약 내용이 완성되자마자 표시됩니다. 첫 번째 부분 다음에 두 번째 부분도 즉시 표시됩니다.",
                "easyExplanation":"완료된 페이지의 쉬운 설명입니다.",
                "evidence":[{"sourceId":"s1","page":1,"quote":"표본 근거"}]}]}}
            """).getAsJsonObject();
        unit.getAsJsonObject("summary").getAsJsonArray("parts").get(0).getAsJsonObject()
            .add("stepFlow",StepFlowTest.fixtureModule());
        StringBuilder longMath=new StringBuilder("$$\n=\\left[");
        for(int n=1;n<=20;n++) {
            if(n>1)longMath.append("+");
            longMath.append("f\\left(\\frac{").append(2*n-1).append("}{40}\\right)");
        }
        longMath.append("\\right]\\frac{1}{20}\n$$");
        JsonObject part=unit.getAsJsonObject("summary").getAsJsonArray("parts").get(0).getAsJsonObject();
        part.addProperty("body",part.get("body").getAsString()+"\n\n"+longMath);
        unit.getAsJsonObject("summary").addProperty("body",part.get("body").getAsString());
        Files.writeString(preview,unit.toString());
        SwingUtilities.invokeAndWait(()->{
            try {
                var key=PdfWorkspace.class.getDeclaredField("liveGenerationKey");key.setAccessible(true);key.set(panel,studyKey(panel));
                JsonObject event=new JsonObject();event.addProperty("type","summary_unit_ready");
                event.addProperty("unit",2);event.addProperty("total",2);event.addProperty("scope","document");
                event.addProperty("selectionPage",0);event.addProperty("path",preview.toString());
                var handler=PdfWorkspace.class.getDeclaredMethod("handleProgress",int.class,JsonObject.class);handler.setAccessible(true);
                handler.invoke(panel,((java.util.concurrent.atomic.AtomicInteger)field(panel,"generation")).get(),event);
            }catch(Exception failure){throw new AssertionError(failure);}
        });
        SwingUtilities.invokeAndWait(()->{});
        // The preview intentionally types the completed section over several timer ticks.
        long previewDeadline=System.currentTimeMillis()+5_000;
        boolean[] previewRendered={false};
        while(System.currentTimeMillis()<previewDeadline) {
            SwingUtilities.invokeAndWait(()->{
                Container live=(Container)field(panel,"summaryScroll");
                previewRendered[0]=containsEditorText(live,"검증을 마친 요약 내용")
                    && containsEditorText(live,"두 번째 부분도 즉시 표시됩니다")
                    && containsEditorText(live,"쉬운 설명 보기");
            });
            if(previewRendered[0])break;
            Thread.sleep(50);
        }
        SwingUtilities.invokeAndWait(()->{
            try {
                if(!((Map<?,?>)field(panel,"liveSummarySections")).containsKey(2))
                    throw new AssertionError("A later completed page waited for the earlier page");
                if(!containsEditorText((Container)field(panel,"summaryScroll"),"검증을 마친 요약 내용")
                    || !containsEditorText((Container)field(panel,"summaryScroll"),"두 번째 부분도 즉시 표시됩니다"))
                    throw new AssertionError("Validated section was not shown immediately");
                Container live=(Container)field(panel,"summaryScroll");
                if(!containsEditorText(live,"쉬운 설명 보기") || !containsEditorText(live,"p.1")
                    || findChild(live,StepFlow.Panel.class)==null)
                    throw new AssertionError("Live section lost easy explanation, PDF link, or module");
                if(findNamedChild(live,"MathScrollPane")==null || containsEditorText(live,"\\left["))
                    throw new AssertionError("Wide live equation was clipped or shown as raw TeX");
                var showTab=PdfWorkspace.class.getDeclaredMethod("showTab",String.class);showTab.setAccessible(true);
                showTab.invoke(panel,"요약");
                layout(panel);
                JScrollPane wideMath=(JScrollPane)findNamedChild(live,"MathScrollPane");
                if(!wideMath.getHorizontalScrollBar().isVisible())
                    throw new AssertionError("Wide equation has no horizontal scrollbar");
                snapshot(wideMath,"wide-math-scroll.png");
                var navigate=PdfWorkspace.class.getDeclaredMethod("navigate",String.class);navigate.setAccessible(true);
                navigate.invoke(panel,"easy:"+studyKey(panel)+"/section-0/part-0");
                if(!containsEditorText(live,"완료된 페이지의 쉬운 설명입니다."))
                    throw new AssertionError("Live easy explanation did not expand");
                var clear=PdfWorkspace.class.getDeclaredMethod("clearLiveSummary");clear.setAccessible(true);clear.invoke(panel);
                var render=PdfWorkspace.class.getDeclaredMethod("renderSummary");render.setAccessible(true);render.invoke(panel);
                if(containsEditorText((Container)field(panel,"summaryScroll"),"요약 생성 중"))
                    throw new AssertionError("Live preview remained after returning to the saved summary view");
            }catch(Exception failure){throw new AssertionError(failure);}
        });
    }
    static boolean containsEditorText(Container parent,String expected) {
        for(Component child:parent.getComponents()) {
            if(child instanceof JEditorPane pane)try {
                if(pane.getDocument().getText(0,pane.getDocument().getLength()).contains(expected))return true;
            }catch(javax.swing.text.BadLocationException ignored){}
            if(child instanceof Container nested && containsEditorText(nested,expected))return true;
        }
        return false;
    }

    private static void assertLensBetweenText(Container parent,String before,String after) {
        int first=-1,lens=-1,last=-1;
        Component[] children=parent.getComponents();
        for(int i=0;i<children.length;i++) {
            Component child=children[i];
            if(child instanceof SlideLens.Panel)lens=i;
            if(child instanceof JEditorPane pane)try {
                String content=pane.getDocument().getText(0,pane.getDocument().getLength());
                if(content.contains(before))first=i;
                if(content.contains(after))last=i;
            }catch(Exception error){throw new RuntimeException(error);}
        }
        if(first<0 || lens<=first || last<=lens)
            throw new AssertionError("SlideLens was not inserted between the related explanation blocks");
    }

    private static void testPdfTextSelection() {
        JsonObject document=JsonParser.parseString("""
            {"pages":[
              {"words":[{"text":"첫째","bbox":[0.10,0.10,0.20,0.14]},
                         {"text":"문장","bbox":[0.25,0.10,0.35,0.14]}],
               "ocrBlocks":[{"duplicateNative":true,"words":[{"text":"중복","bbox":[0.4,0.1,0.5,0.14]}]}]},
              {"words":[{"text":"다음","bbox":[0.10,0.10,0.20,0.14]}],
               "ocrBlocks":[{"words":[{"text":"페이지","bbox":[0.25,0.10,0.35,0.14]}]}]}
            ]}
            """).getAsJsonObject();
        PdfTextSelection selection=new PdfTextSelection();
        Rectangle firstPage=new Rectangle(50,80,1000,1200);
        PdfTextSelection.Word first=selection.hit(document,1,firstPage,new Point(200,225),true);
        if(first==null || !first.text().equals("첫째") || first.bounds(firstPage).x!=150)
            throw new AssertionError("PDF text hit testing or zoom coordinates");
        if(selection.words(document,1).size()!=2 || selection.words(document,2).size()!=1)
            throw new AssertionError("Legacy OCR must not enter new text selections");
        selection.press(first);
        selection.drag(selection.words(document,2).getLast());
        if(!selection.hasSelection() || !selection.text(document).equals("첫째 문장\n\n다음"))
            throw new AssertionError("PDF cross-page selection text");
        selection.clear();
        if(selection.hasSelection())throw new AssertionError("PDF selection clear");
    }
    static JComponent findNamedChild(Container parent,String simpleName) {
        for(Component child:parent.getComponents()) {
            if(child.getClass().getSimpleName().equals(simpleName))return (JComponent)child;
            if(child instanceof Container nested) {
                JComponent found=findNamedChild(nested,simpleName);
                if(found!=null)return found;
            }
        }
        return null;
    }
    static void snapshot(JComponent panel,String name)throws Exception{
        BufferedImage image=new BufferedImage(panel.getWidth(),panel.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();panel.printAll(g);g.dispose();ImageIO.write(image,"png",ROOT.resolve(name).toFile());
    }
    static void layout(Container p){p.doLayout();for(Component c:p.getComponents())if(c instanceof Container child)layout(child);}
    static PDFont font(PDDocument doc)throws Exception{
        String configured=System.getProperty("synesis.test.font", "");
        Path[] candidates={
            configured.isBlank()?Path.of("missing-test-font"):Path.of(configured),
            Path.of("src/test/resources/fonts/NanumGothic-Regular.ttf"),
            Path.of("C:/Windows/Fonts/malgun.ttf"),
        };
        for(Path candidate:candidates)if(Files.isRegularFile(candidate))
            return PDType0Font.load(doc,candidate.toFile());
        throw new java.io.IOException("Korean test font missing; set -Dsynesis.test.font=/path/to/font.ttf");
    }
    static void line(PDPageContentStream stream,PDFont font,int size,float x,float y,String text)throws Exception{
        stream.beginText();stream.setFont(font,size);stream.newLineAtOffset(x,y);stream.showText(text);stream.endText();
    }
    static void fixtures()throws Exception {
        try(PDDocument doc=new PDDocument()) {
            PDPage page=new PDPage(new PDRectangle(400,300));page.setCropBox(new PDRectangle(40,30,300,200));page.setRotation(90);doc.addPage(page);
            try(PDPageContentStream stream=new PDPageContentStream(doc,page)) {
                Color[] colors={Color.RED,Color.GREEN,Color.BLUE,Color.YELLOW};
                for(int n=0;n<4;n++) {
                    stream.setNonStrokingColor(colors[n]);stream.addRect(40+(n%2)*150,30+(n/2)*100,150,100);stream.fill();
                }
            }
            doc.save(ROOT.resolve("crop-rotation.pdf").toFile());
        }
        try(PdfSource pdf=PdfSource.open(ROOT.resolve("crop-rotation.pdf"),ROOT.resolve("rotation-cache"))) {
            BufferedImage rendered=pdf.render(1,1);ImageIO.write(rendered,"png",ROOT.resolve("crop-rotation-java.png").toFile());
            BufferedImage crop=SlideLens.crop(pdf,new SlideLens.Request("test",1,new double[]{0,0,.5,.5},true,false));
            if((crop.getRGB(crop.getWidth()/2,crop.getHeight()/2)&0xffffff)!=(rendered.getRGB(rendered.getWidth()/4,rendered.getHeight()/4)&0xffffff))
                throw new AssertionError("Rotated CropBox crop does not match rendered coordinates");
        }
        try(PDDocument doc=new PDDocument()){
            PDFont font=font(doc);
            String[][] paragraphs={
                {"에너지 보존 · Energy conservation","외부와 에너지를 교환하지 않는 계에서 총에너지는 일정하다.","운동 에너지와 위치 에너지는 서로 전환될 수 있다.","이 자료의 그림과 수식은 정확한 기호를 원문에서 확인한다."},
                {"일과 힘 · Work and force","일은 힘과 이동 방향의 관계로 정의한다.","일의 단위는 줄이다. 영어로는 joule이며 기호는 J이다.","이 페이지의 고유 검색어: 회전운동"},
                {"에너지 보존의 보충 설명","마찰이 작용하면 역학적 에너지 일부가 열에너지로 바뀐다.","총에너지는 보존되지만 역학적 에너지만 보면 줄어들 수 있다.","첫 페이지에서 정의한 에너지 보존 개념을 여기서 보충한다."}};
            for(String[] rows:paragraphs){PDPage page=new PDPage(PDRectangle.A4);doc.addPage(page);try(PDPageContentStream s=new PDPageContentStream(doc,page)){for(int j=0;j<rows.length;j++)line(s,font,j==0?22:13,44,760-j*50,rows[j]);}}
            doc.save(ROOT.resolve("text.pdf").toFile());
        }
        BufferedImage scan=new BufferedImage(1000,1300,BufferedImage.TYPE_INT_RGB);Graphics2D g=scan.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,1000,1300);g.setColor(Color.BLACK);g.setFont(new Font("Malgun Gothic",Font.BOLD,40));g.drawString("에너지 보존 법칙",70,140);g.setFont(new Font("Malgun Gothic",Font.PLAIN,29));g.drawString("Energy conservation - 42 joules",70,220);g.drawString("닫힌 계에서 총에너지는 일정하다.",70,290);g.drawString("기호와 단위: E = 42 J",70,360);g.dispose();ImageIO.write(scan,"png",ROOT.resolve("scan.png").toFile());
        try(PDDocument doc=new PDDocument()){PDPage page=new PDPage(PDRectangle.A4);doc.addPage(page);try(PDPageContentStream s=new PDPageContentStream(doc,page)){s.drawImage(LosslessFactory.createFromImage(doc,scan),0,0,page.getMediaBox().getWidth(),page.getMediaBox().getHeight());}doc.save(ROOT.resolve("scan.pdf").toFile());}
        try(PDDocument doc=new PDDocument()){
            PDFont font=font(doc);PDPage page=new PDPage(PDRectangle.A4);doc.addPage(page);
            try(PDPageContentStream s=new PDPageContentStream(doc,page)){
                line(s,font,20,35,780,"표 · 수식 · 그림 품질 점검");
                line(s,font,12,35,720,"물리량       값       단위");line(s,font,12,35,690,"에너지       42        J");line(s,font,12,35,660,"시간          3        s");
                line(s,font,12,330,720,"오른쪽 단: 독립적인 설명");line(s,font,12,330,690,"두 단 읽기 순서를 확인한다.");
                line(s,font,16,35,570,"E = m c^2     F = m a");s.moveTo(35,630);s.lineTo(250,630);s.stroke();
                s.drawImage(LosslessFactory.createFromImage(doc,scan),45,80,280,364);
            }doc.save(ROOT.resolve("table-math-image.pdf").toFile());
        }
        try(PDDocument doc=new PDDocument()){PDFont font=font(doc);for(int i=1;i<=120;i++){PDPage p=new PDPage(PDRectangle.A4);doc.addPage(p);try(PDPageContentStream s=new PDPageContentStream(doc,p)){line(s,font,16,44,760,"강의자료 "+i+"쪽");line(s,font,12,44,700,i==117?"장문검색표식: 엔트로피 증가 법칙":"같은 문서를 반복 분석하지 않고 원문을 캐시한다.");}}doc.save(ROOT.resolve("long-120.pdf").toFile());}
        Files.writeString(ROOT.resolve("invalid.pdf"),"not a PDF");
    }
}
