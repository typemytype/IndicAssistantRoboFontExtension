from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Transform

from glyphNameFormatter.reader import u2c

from mojo.subscriber import Subscriber, registerGlyphEditorSubscriber


indicAssistantKey = "Indic.Assistant"
anchorCloudPreviewKey = f"{indicAssistantKey}.anchorCloudPreview"


class IndicGlyphEditorAssistant(Subscriber):

    debug = True

    def build(self):
        glyphEditor = self.getGlyphEditor()

        container = glyphEditor.extensionContainer(
            identifier=indicAssistantKey,
            location='background',
            clear=True
        )
        previewContainer = glyphEditor.extensionContainer(
            identifier=indicAssistantKey,
            location='preview',
            clear=True
        )
        self.anchorCloud = container.appendPathSublayer(
            fillColor=(.3, 0, 1, .3),
            strokeColor=(0, 1, 1, 1),
            strokeWidth=1,
        )
        self.previewAnchorCloud = previewContainer.appendPathSublayer(
            fillColor=(0, 0, 0, .5),
        )
        self.calculateAnchorCloud(glyphEditor.getGlyph())

    def destroy(self):
        glyphEditor = self.getGlyphEditor()
        container = glyphEditor.extensionContainer(indicAssistantKey, location='background')
        container.clearSublayers()
        container = glyphEditor.extensionContainer(indicAssistantKey, location='preview')
        container.clearSublayers()

    def glyphEditorDidSetGlyph(self, info):
        self.clearAnchorMap()
        self.calculateAnchorCloud(info['glyph'])

    def glyphEditorGlyphDidChangeAnchors(self, info):
        self.clearAnchorMap()
        self.calculateAnchorCloud(info["glyph"])

    # Anchor cloud

    def calculateAnchorCloud(self, glyph):
        if glyph is None:
            self.anchorCloud.setPath(None)
            self.previewAnchorCloud.setPath(None)
            return

        anchorMap = self.getAnchorCloudMapForGlyph(glyph)

        pen = self.anchorCloud.getPen(glyphSet=None, clear=True)

        previewMap = glyph.lib.get(anchorCloudPreviewKey, dict())

        for anchor in glyph.anchors:
            cloudAnchors = anchorMap.get(anchor.name, [])
            if cloudAnchors:
                previewGlyphName = previewMap.get(anchor.name, cloudAnchors[-1].glyph.name)
                previewGlyph = None
                for cloudAnchor in cloudAnchors:
                    if cloudAnchor.glyph.name == previewGlyphName:
                        previewGlyph = cloudAnchor.glyph
                        break
                if previewGlyph is not None:
                    anchorTransformPen = TransformPen(pen, (1, 0, 0, 1, anchor.x - cloudAnchor.x, anchor.y - cloudAnchor.y))
                    cloudAnchor.glyph.draw(anchorTransformPen)

        self.previewAnchorCloud.setPath(self.anchorCloud.getPath())

    _anchorCloudMap = dict()

    def getAnchorCloudMapForGlyph(self, glyph):
        layer = glyph.layer
        if layer is None:
            self.clearAnchorMap()

        if not self._anchorCloudMap:
            for layerGlyph in layer:
                if layerGlyph.name == glyph.name:
                    continue
                for anchor in layerGlyph.anchors:
                    if anchor.name.startswith("_"):
                        key = anchor.name[1:]
                        if key not in self._anchorCloudMap:
                            self._anchorCloudMap[key] = []
                        self._anchorCloudMap[key].append(anchor)
        return self._anchorCloudMap

    def clearAnchorMap(self):
        self._anchorCloudMap.clear()

    # Conjunct composition

    def glyphEditorComponentWillBeAdded(self, notification):
        glyph = notification["glyph"].asFontParts()
        component = notification["component"].asFontParts()

        layer = glyph.layer
        if component.baseGlyph not in layer:
            return

        baseGlyphlayer = layer[component.baseGlyph]

        # todo:
        # copy all anchors while adding a component, overwrite if it already exist
        if len(glyph.components) > 1:
            shiftX = glyph.width
            shiftY = 0

            glyph.width += baseGlyphlayer.width
            # position the anchor with the component.baseGlyph anchor when the component is a mark: rakar-deva + Mn
            if baseGlyphlayer.name in ["rakar-deva", "nukta-deva", "halant-deva"] or u2c(baseGlyphlayer.unicode) == "Mn":
                shiftX = 0
                anchorMap = dict()
                for anchor in glyph.anchors:
                    anchorMap[anchor.name] = anchor

                for baseGlyphAnchor in baseGlyphlayer.anchors:
                    if baseGlyphAnchor.name.startswith("_") and baseGlyphAnchor.name[1:] in anchorMap:
                        anchor = anchorMap[baseGlyphAnchor.name[1:]]
                        shiftX = anchor.x - baseGlyphAnchor.x
                        shiftY = anchor.y - baseGlyphAnchor.y

            component.moveBy((shiftX, shiftY))
            glyph.changed()

    def glyphEditorWantsContextualMenuItems(self, notification):
        glyphEditor = self.getGlyphEditor()
        glyph = glyphEditor.getGlyph()

        anchorMap = self.getAnchorCloudMapForGlyph(glyph)
        previewMap = glyph.lib.get(anchorCloudPreviewKey, dict())

        anchorMenu = list()

        for anchor in glyph.anchors:
            if anchor.name in anchorMap:
                cloudAnchors = anchorMap[anchor.name]
                items = [
                    dict(title=cloudAnchor.glyph.name, callback=self.contextualMenuAncherCloudSelection, state=int(previewMap.get(anchor.name) == cloudAnchor.glyph.name))
                    for cloudAnchor in cloudAnchors
                ]
                anchorMenu.append((anchor.name, items))

        itemDescriptions = notification["itemDescriptions"]
        itemDescriptions.extend([
            ("Decompose All and Copy Anchors", self.contextualMenuDecomposeComponents),
            ("Copy Anchors from Components", self.contextualMenuCopyAnchorsFromComponents),
            "----",
            ("Preview Anchor Cloud", anchorMenu)
        ])

    def _copyAnchorsAndDecompose(self, shouldDecompose=True):
        glyphEditor = self.getGlyphEditor()
        glyph = glyphEditor.getGlyph()
        if glyph is None:
            return
        layer = glyph.layer

        anchorMap = dict()
        for anchor in glyph.anchors:
            anchorMap[anchor.name] = anchor

        selectedComponents = [component for component in glyph.components if component.selected]
        if not selectedComponents:
            selectedComponents = glyph.components

        undoMessage = "Copy Anchors"
        if shouldDecompose:
            undoMessage += " and Decompose"

        glyph.prepareUndo(undoMessage)
        for component in selectedComponents:
            if component.baseGlyph in layer:
                componentGlyph = layer[component.baseGlyph]
                transformation = Transform(*component.transformation)
                for anchor in componentGlyph.anchors:
                    x, y = anchor.x, anchor.y
                    x, y = transformation.transformPoint((x, y))
                    if anchor.name not in anchorMap:
                        glyph.appendAnchor(
                            dict(
                                x=x,
                                y=y,
                                name=anchor.name,
                                color=anchor.color,
                            )
                        )
                    else:
                        anchor = anchorMap[anchor.name]
                        anchor.x = x
                        anchor.y = y

        if shouldDecompose:
            glyph.decomposeAllComponents()

        glyph.performUndo()

    def contextualMenuDecomposeComponents(self, sender):
        self._copyAnchorsAndDecompose()

    def contextualMenuCopyAnchorsFromComponents(self, sender):
        self._copyAnchorsAndDecompose(shouldDecompose=False)

    def contextualMenuAncherCloudSelection(self, sender):
        glyphEditor = self.getGlyphEditor()
        glyph = glyphEditor.getGlyph()

        anchorName = sender.parentItem().title()
        glyphName = sender.title()

        if anchorCloudPreviewKey not in glyph.lib:
            glyph.lib[anchorCloudPreviewKey] = dict()
        if glyph.lib[anchorCloudPreviewKey].get(anchorName) == glyphName:
            del glyph.lib[anchorCloudPreviewKey][anchorName]
        else:
            glyph.lib[anchorCloudPreviewKey][anchorName] = glyphName

        self.calculateAnchorCloud(glyph)


if __name__ == '__main__':
    registerGlyphEditorSubscriber(IndicGlyphEditorAssistant)
